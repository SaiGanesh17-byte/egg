'use client'

import React, { useState, useEffect } from 'react';
import { RepoSelector } from '@/components/RepoSelector';
import { SidebarTree, FileTreeNode } from '@/components/SidebarTree';
import { EggLogo } from '@/components/EggLogo';
import { ConfidenceCard } from '@/components/ConfidenceCard';
import { 
  FolderIcon, 
  Settings, 
  Layers, 
  FileText, 
  Terminal, 
  HelpCircle, 
  ArrowLeft,
  Loader2,
  Code,
  Tag,
  Share2,
  CheckCircle2,
  Clock,
  Database,
  Cpu,
  Network,
  HardDrive,
  FolderOpen
} from 'lucide-react';

interface FileDetails {
  content: string;
  symbols: Array<{
    id: string;
    name: string;
    kind: string;
    start_line: number;
    end_line: number;
    signature: string | null;
  }>;
  edges: Array<{
    source: string;
    target: string;
    type: string;
    label: string | null;
  }>;
}

interface DbStats {
  total_symbols: number;
  total_edges: number;
  symbols_summary: Record<string, number>;
  edges_summary: Record<string, number>;
  sql_tables: Array<{ id: string; name: string }>;
  confidence_summary?: {
    high: number;
    medium: number;
    low: number;
  };
}

export default function Home() {
  const [repoPath, setRepoPath] = useState<string | null>(null);
  const [fileTree, setFileTree] = useState<FileTreeNode[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileDetails, setFileDetails] = useState<FileDetails | null>(null);
  const [dbStats, setDbStats] = useState<DbStats | null>(null);
  
  // App Config States
  const [globalDbPath, setGlobalDbPath] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [tempPathInput, setTempPathInput] = useState('');
  
  const [history, setHistory] = useState<string[]>([]);
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3>(1);
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [statsData, setStatsData] = useState<{ total: number; indexed: number; nodes: number } | null>(null);

  const [isLoadingTree, setIsLoadingTree] = useState(false);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [isLoadingStats, setIsLoadingStats] = useState(false);
  const [activeTab, setActiveTab] = useState<'code' | 'symbols' | 'graph'>('code');

  // Load configuration and history on mount
  useEffect(() => {
    const savedPath = localStorage.getItem('egg_global_db_path');
    if (savedPath) {
      setGlobalDbPath(savedPath);
      setTempPathInput(savedPath);
    } else {
      // Force settings setup if not configured
      setShowSettings(true);
    }

    const savedHistory = localStorage.getItem('egg_scan_history');
    if (savedHistory) {
      try {
        setHistory(JSON.parse(savedHistory));
      } catch (e) {
        console.error('Failed to parse history:', e);
      }
    }
  }, []);

  const handleSaveSettings = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    const cleanPath = tempPathInput.trim();
    if (!cleanPath) {
      alert("Database storage path is mandatory.");
      return;
    }
    localStorage.setItem('egg_global_db_path', cleanPath);
    setGlobalDbPath(cleanPath);
    setShowSettings(false);
  };

  const selectSettingsFolder = async () => {
    try {
      if (typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window) {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: "Select Centralized CPG Databases Folder"
        });
        if (selected && typeof selected === 'string') {
          setTempPathInput(selected);
        }
      } else {
        alert("Directory picker requires native Tauri runtime. Please enter path directly.");
      }
    } catch (err: any) {
      console.error(err);
    }
  };

  const handleScanStart = () => {
    setCurrentStep(2);
  };

  const handleScanComplete = (path: string, stats?: any) => {
    setRepoPath(path);
    setCurrentStep(3);
    
    // Save to history
    const updatedHistory = [path, ...history.filter(p => p !== path)].slice(0, 5);
    setHistory(updatedHistory);
    localStorage.setItem('egg_scan_history', JSON.stringify(updatedHistory));

    // Open Save Modal Popup
    if (stats) {
      setStatsData({
        total: stats.total_files || 0,
        indexed: stats.indexed_files || 0,
        nodes: stats.node_count || 0,
      });
      setShowSaveModal(true);
    }
    
    fetchFileTree(path);
    fetchDbStats(path);
  };

  const fetchFileTree = async (path: string) => {
    setIsLoadingTree(true);
    try {
      const response = await fetch(`http://localhost:8000/api/tree?repo_path=${encodeURIComponent(path)}`);
      if (response.ok) {
        const data = await response.json();
        setFileTree(data.tree);
      }
    } catch (err) {
      console.error('Failed to fetch file tree:', err);
    } finally {
      setIsLoadingTree(false);
    }
  };

  const fetchDbStats = async (path: string) => {
    if (!globalDbPath) return;
    setIsLoadingStats(true);
    try {
      const response = await fetch(
        `http://localhost:8000/api/db_stats?repo_path=${encodeURIComponent(path)}&db_storage_path=${encodeURIComponent(globalDbPath)}`
      );
      if (response.ok) {
        const data = await response.json();
        setDbStats(data);
      }
    } catch (err) {
      console.error('Failed to fetch DB stats:', err);
    } finally {
      setIsLoadingStats(false);
    }
  };

  const handleFileSelect = async (filePath: string) => {
    if (!repoPath || !globalDbPath) return;
    setSelectedFile(filePath);
    setIsLoadingDetails(true);
    setFileDetails(null);
    try {
      const response = await fetch(
        `http://localhost:8000/api/file_details?repo_path=${encodeURIComponent(repoPath)}&db_storage_path=${encodeURIComponent(globalDbPath)}&file_path=${encodeURIComponent(filePath)}`
      );
      if (response.ok) {
        const data = await response.json();
        setFileDetails({
          content: data.content,
          symbols: data.symbols,
          edges: data.edges,
        });
      }
    } catch (err) {
      console.error('Failed to fetch file details:', err);
    } finally {
      setIsLoadingDetails(false);
    }
  };

  const selectHistoryRepo = async (path: string) => {
    if (!globalDbPath) return;
    handleScanStart();
    try {
      const response = await fetch('http://localhost:8000/api/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: path, db_storage_path: globalDbPath }),
      });
      if (response.ok) {
        const data = await response.json();
        handleScanComplete(path, data);
      } else {
        throw new Error('Failed to scan history repo');
      }
    } catch (e) {
      console.error(e);
      setCurrentStep(1);
      alert(`Failed to load: ${path}. Make sure the directory exists and the backend is running.`);
    }
  };

  const resetWorkspace = () => {
    setRepoPath(null);
    setFileTree([]);
    setSelectedFile(null);
    setFileDetails(null);
    setDbStats(null);
    setCurrentStep(1);
  };

  const renderStepper = () => {
    return (
      <div className="flex items-center justify-center space-x-6 py-3 px-6 rounded-xl border border-zinc-900 bg-zinc-950 font-sans max-w-xl mx-auto shadow-inner text-xs">
        <div className="flex items-center space-x-2">
          <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors ${
            currentStep === 1 ? 'bg-purple-600 text-white ring-4 ring-purple-950' : 'bg-zinc-800 text-zinc-400'
          }`}>1</div>
          <span className={currentStep === 1 ? 'text-zinc-100 font-medium' : 'text-zinc-500'}>Select Folder</span>
        </div>
        <div className="w-12 h-0.5 bg-zinc-900" />
        <div className="flex items-center space-x-2">
          <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors ${
            currentStep === 2 ? 'bg-purple-600 text-white ring-4 ring-purple-950' : 'bg-zinc-800 text-zinc-400'
          }`}>2</div>
          <span className={currentStep === 2 ? 'text-zinc-100 font-medium' : 'text-zinc-500'}>Build CPG Graph</span>
        </div>
        <div className="w-12 h-0.5 bg-zinc-900" />
        <div className="flex items-center space-x-2">
          <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-colors ${
            currentStep === 3 ? 'bg-purple-600 text-white ring-4 ring-purple-950' : 'bg-zinc-800 text-zinc-400'
          }`}>3</div>
          <span className={currentStep === 3 ? 'text-zinc-100 font-medium' : 'text-zinc-500'}>Explore CPG DB</span>
        </div>
      </div>
    );
  };

  // -------------------------------------------------------------
  // Mandatory Settings Modal View
  // -------------------------------------------------------------
  if (showSettings || !globalDbPath) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-zinc-950 text-zinc-100 p-6 selection:bg-zinc-850 font-sans">
        <div className="w-full max-w-md border border-zinc-900 bg-zinc-950/70 backdrop-blur-xl p-6 rounded-2xl shadow-2xl space-y-6">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-purple-950/40 border border-purple-900/30 rounded-lg text-purple-400">
              <Settings className="w-6 h-6 animate-spin" />
            </div>
            <div>
              <h2 className="text-lg font-bold tracking-tight text-white">App Settings Setup</h2>
              <p className="text-xs text-zinc-550">CPG Databases Global Directory Config</p>
            </div>
          </div>

          <div className="space-y-4 text-xs text-zinc-400 leading-relaxed">
            <p>
              Welcome to the **Egg CPG Engine**. For security and folder structure integrity, code graphs are stored inside a single centralized folder. 
            </p>
            <p className="font-semibold text-zinc-300">
              Please specify a directory path where all SQLite CPG databases will be saved:
            </p>
          </div>

          <form onSubmit={handleSaveSettings} className="space-y-4">
            <div>
              <label htmlFor="settings-db-path" className="block text-[10px] uppercase font-bold text-zinc-500 mb-1.5 tracking-wider">
                Centralized Databases Storage Directory
              </label>
              <div className="flex space-x-2">
                <input
                  id="settings-db-path"
                  type="text"
                  placeholder="e.g. /Users/username/egg_databases"
                  value={tempPathInput}
                  onChange={(e) => setTempPathInput(e.target.value)}
                  className="flex-1 px-3 py-2 bg-zinc-900/50 border border-zinc-800 rounded-lg focus:outline-none focus:ring-1 focus:ring-purple-600 focus:border-purple-700 text-xs font-mono text-zinc-200"
                  required
                />
                <button
                  type="button"
                  onClick={selectSettingsFolder}
                  className="px-3 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 rounded-lg text-zinc-400 transition-colors"
                  title="Choose Directory"
                >
                  <FolderOpen className="w-4 h-4" />
                </button>
              </div>
            </div>

            <div className="flex space-x-3 pt-2">
              <button
                type="submit"
                disabled={!tempPathInput.trim()}
                className="flex-1 py-2.5 px-4 bg-white text-black hover:bg-zinc-200 disabled:bg-zinc-800 disabled:text-zinc-600 text-xs font-semibold rounded-lg transition-colors shadow-md"
              >
                Save Configuration
              </button>
              {globalDbPath && (
                <button
                  type="button"
                  onClick={() => {
                    setTempPathInput(globalDbPath);
                    setShowSettings(false);
                  }}
                  className="py-2.5 px-4 bg-zinc-900 hover:bg-zinc-850 border border-zinc-800 text-zinc-400 text-xs font-semibold rounded-lg transition-colors"
                >
                  Cancel
                </button>
              )}
            </div>
          </form>
        </div>
      </div>
    );
  }

  if (!repoPath) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-zinc-950 text-zinc-100 p-6 selection:bg-zinc-850">
        
        {/* Settings Panel access trigger (Top Right) */}
        <div className="absolute top-6 right-6">
          <button
            onClick={() => {
              setTempPathInput(globalDbPath);
              setShowSettings(true);
            }}
            className="flex items-center space-x-2 py-1.5 px-3 bg-zinc-950 hover:bg-zinc-900 border border-zinc-900 text-zinc-400 hover:text-white rounded-lg text-xs font-medium transition-colors"
            title="Configure settings file"
          >
            <Settings className="w-3.5 h-3.5" />
            <span>App Settings</span>
          </button>
        </div>

        {/* Stepper on top */}
        <div className="w-full max-w-xl mb-12">
          {renderStepper()}
        </div>

        <div className="flex flex-col items-center space-y-3 mb-8">
          <EggLogo className="w-16 h-16 shadow-2xl" />
          <h1 className="text-2xl font-bold tracking-tight text-white">Egg CPG Engine</h1>
          <p className="text-zinc-500 text-sm max-w-md text-center">
            Deterministically extract Code Property Graphs (AST, CFG, DFG, Call graphs) across multi-language codebases.
          </p>
        </div>

        {/* Custom scanning callbacks */}
        <div className="w-full max-w-xl">
          <RepoSelector 
            onScanStart={handleScanStart} 
            onScanComplete={(path) => {
              // Trigger temporary fetch to get node counts for the modal
              fetch(`http://localhost:8000/api/scan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ repo_path: path, db_storage_path: globalDbPath })
              })
              .then(res => res.json())
              .then(data => handleScanComplete(path, data))
              .catch(() => handleScanComplete(path));
            }} 
          />
        </div>

        {/* Scan History list */}
        {history.length > 0 && currentStep === 1 && (
          <div className="w-full max-w-xl mt-10 border border-zinc-900 bg-zinc-950/40 p-5 rounded-2xl space-y-3">
            <div className="flex items-center space-x-2 text-zinc-400 text-xs font-semibold uppercase tracking-wider">
              <Clock className="w-3.5 h-3.5" />
              <span>Recent Workspaces</span>
            </div>
            <div className="divide-y divide-zinc-900">
              {history.map((path) => (
                <button
                  key={path}
                  onClick={() => selectHistoryRepo(path)}
                  className="w-full flex items-center justify-between py-2.5 text-left text-xs font-mono text-zinc-400 hover:text-white hover:bg-zinc-900/30 px-2 rounded-lg transition-colors group"
                >
                  <span className="truncate pr-4">{path}</span>
                  <span className="text-[10px] text-zinc-650 group-hover:text-purple-400 font-sans transition-colors font-medium">Quick Load &rarr;</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Loading state indicator during CPG generation */}
        {currentStep === 2 && (
          <div className="mt-8 flex flex-col items-center space-y-2 text-xs text-zinc-400">
            <Loader2 className="w-5 h-5 animate-spin text-purple-500" />
            <span>Parsing source ASTs & resolving data flows...</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-screen bg-zinc-950 text-zinc-100 font-sans selection:bg-zinc-850">
      
      {/* CPG Database Saved Modal Notification */}
      {showSaveModal && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-md flex items-center justify-center z-50 p-4 font-sans">
          <div className="w-full max-w-md border border-zinc-900 bg-zinc-950 p-6 rounded-2xl shadow-2xl space-y-4">
            <div className="flex items-center space-x-2.5 text-emerald-500">
              <CheckCircle2 className="w-6 h-6" />
              <h3 className="text-lg font-bold text-white tracking-tight">CPG Saved to Database</h3>
            </div>
            <p className="text-xs text-zinc-400 leading-relaxed">
              Deterministic Code Property Graph successfully compiled and indexed. All nodes and edges are stored locally in the centralized databases directory.
            </p>
            <div className="p-3 bg-zinc-900 border border-zinc-800 rounded-xl text-[10px] font-mono space-y-1.5 text-zinc-350">
              <div className="break-all"><span className="text-zinc-500 font-semibold">Location:</span> {globalDbPath}/{repoPath ? repoPath.replace(/^\/|\\/, "").replace(/\//g, "_").replace(/\\/g, "_").replace(/:/g, "") : "repo"}/graph.db</div>
              <div><span className="text-zinc-500 font-semibold">CPG Nodes (Symbols):</span> {statsData?.nodes.toLocaleString()}</div>
              <div><span className="text-zinc-500 font-semibold">Files Scanned:</span> {statsData?.total} ({statsData?.indexed} indexed/updated)</div>
            </div>
            <div className="flex justify-end pt-2">
              <button
                onClick={() => setShowSaveModal(false)}
                className="py-2 px-5 bg-white hover:bg-zinc-200 text-black text-xs font-semibold rounded-lg shadow-md transition-colors"
              >
                Proceed to CPG Explorer
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar Navigation */}
      <aside className="w-80 flex flex-col border-r border-zinc-900 bg-zinc-950">
        {/* Header */}
        <div className="p-4 border-b border-zinc-900 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <EggLogo className="w-7 h-7" />
            <span className="font-semibold text-sm tracking-tight text-white">Egg Workspace</span>
          </div>
          <button 
            onClick={resetWorkspace} 
            className="p-1.5 hover:bg-zinc-900 hover:text-white rounded border border-zinc-900 text-zinc-400 transition-colors"
            title="Change Repository"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Tree container */}
        <div className="flex-1 overflow-y-auto p-3">
          <div className="flex items-center justify-between mb-2 px-2 text-[10px] text-zinc-500 font-semibold uppercase tracking-wider">
            <span>Repository Files</span>
            <FolderIcon className="w-3 h-3" />
          </div>
          {isLoadingTree ? (
            <div className="flex items-center justify-center py-8 text-zinc-500 space-x-2 text-xs">
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Reading folder structure...</span>
            </div>
          ) : (
            <SidebarTree 
              tree={fileTree} 
              onFileSelect={handleFileSelect} 
              selectedFilePath={selectedFile} 
            />
          )}
        </div>

        {/* Footer info showing Repo and CPG SQLite DB paths */}
        <div className="p-3 border-t border-zinc-900 bg-zinc-950 text-[10px] text-zinc-500 font-mono space-y-1">
          <div className="truncate"><span className="text-zinc-600 font-semibold">Repo:</span> {repoPath}</div>
          <div className="truncate text-emerald-500/90"><span className="text-zinc-600 font-semibold">DB Dir:</span> {globalDbPath}</div>
        </div>
      </aside>

      {/* Main Panel */}
      <main className="flex-1 flex flex-col min-w-0 bg-zinc-950">
        
        {/* Horizontal stepper on top inside CPG Workspace too */}
        <div className="w-full bg-zinc-950 border-b border-zinc-900 py-2.5 px-6 flex justify-between items-center">
          <span className="text-[10px] text-zinc-500 font-mono uppercase">deterministic CPG visualizer</span>
          {renderStepper()}
        </div>

        {selectedFile ? (
          <div className="flex-1 flex flex-col min-h-0">
            {/* File header */}
            <div className="px-6 py-4 border-b border-zinc-900 flex items-center justify-between bg-zinc-950">
              <div>
                <h2 className="text-sm font-semibold text-white tracking-tight font-mono">{selectedFile}</h2>
                <p className="text-[10px] text-zinc-500 mt-0.5">Code Property Graph representation layer</p>
              </div>
              
              {/* Tab Navigation */}
              <div className="flex bg-zinc-900/60 p-0.5 border border-zinc-800 rounded-lg">
                <button
                  onClick={() => setActiveTab('code')}
                  className={`flex items-center space-x-1.5 px-3 py-1 text-xs rounded-md transition-all duration-150 ${
                    activeTab === 'code' ? 'bg-zinc-850 text-white font-medium shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  <Code className="w-3.5 h-3.5" />
                  <span>Code</span>
                </button>
                <button
                  onClick={() => setActiveTab('symbols')}
                  className={`flex items-center space-x-1.5 px-3 py-1 text-xs rounded-md transition-all duration-150 ${
                    activeTab === 'symbols' ? 'bg-zinc-850 text-white font-medium shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  <Tag className="w-3.5 h-3.5" />
                  <span>Symbols</span>
                </button>
                <button
                  onClick={() => setActiveTab('graph')}
                  className={`flex items-center space-x-1.5 px-3 py-1 text-xs rounded-md transition-all duration-150 ${
                    activeTab === 'graph' ? 'bg-zinc-850 text-white font-medium shadow-sm' : 'text-zinc-400 hover:text-zinc-200'
                  }`}
                >
                  <Share2 className="w-3.5 h-3.5" />
                  <span>Graph Edges</span>
                </button>
              </div>
            </div>

            {/* Tab content panel */}
            <div className="flex-1 overflow-y-auto p-6 min-h-0 bg-zinc-950">
              {isLoadingDetails ? (
                <div className="h-full flex flex-col items-center justify-center text-zinc-550 space-y-2 text-xs">
                  <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
                  <span>Querying CPG mappings...</span>
                </div>
              ) : fileDetails ? (
                <>
                  {activeTab === 'code' && (
                    <div className="h-full flex flex-col">
                      <pre className="flex-1 font-mono text-xs text-zinc-300 bg-zinc-950 p-4 rounded-xl border border-zinc-900 overflow-auto leading-relaxed whitespace-pre select-text">
                        {fileDetails.content}
                      </pre>
                    </div>
                  )}

                  {activeTab === 'symbols' && (
                    <div className="space-y-4">
                      <div className="border border-zinc-900 rounded-xl overflow-hidden bg-zinc-950">
                        <table className="w-full text-left border-collapse text-xs">
                          <thead>
                            <tr className="bg-zinc-900/60 border-b border-zinc-900 text-zinc-400 font-medium">
                              <th className="p-3">Symbol ID</th>
                              <th className="p-3">Name</th>
                              <th className="p-3">Kind</th>
                              <th className="p-3">Lines</th>
                              <th className="p-3">Signature</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-zinc-900 font-mono text-zinc-300">
                            {fileDetails.symbols.length === 0 ? (
                              <tr>
                                <td colSpan={5} className="p-4 text-center text-zinc-500">No CPG symbols discovered in this file.</td>
                              </tr>
                            ) : (
                              fileDetails.symbols.map((sym) => (
                                <tr key={sym.id} className="hover:bg-zinc-900/40">
                                  <td className="p-3 text-zinc-500 text-[10px] break-all">{sym.id}</td>
                                  <td className="p-3 text-white font-medium">{sym.name}</td>
                                  <td className="p-3">
                                    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                      sym.kind === 'CLASS' ? 'bg-indigo-950/40 text-indigo-400 border border-indigo-900/30' :
                                      sym.kind === 'FUNCTION' ? 'bg-emerald-950/40 text-emerald-400 border border-emerald-900/30' :
                                      'bg-zinc-900 text-zinc-400 border border-zinc-800'
                                    }`}>
                                      {sym.kind}
                                    </span>
                                  </td>
                                  <td className="p-3 text-zinc-400">{sym.start_line}-{sym.end_line}</td>
                                  <td className="p-3 text-zinc-400 text-[10px] truncate max-w-xs">{sym.signature || '-'}</td>
                                </tr>
                              ))
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  {activeTab === 'graph' && (
                    <div className="space-y-4">
                      <div className="border border-zinc-900 rounded-xl overflow-hidden bg-zinc-950">
                        <table className="w-full text-left border-collapse text-xs">
                          <thead>
                            <tr className="bg-zinc-900/60 border-b border-zinc-900 text-zinc-400 font-medium">
                              <th className="p-3">Source Node</th>
                              <th className="p-3">Relationship</th>
                              <th className="p-3">Target Node</th>
                              <th className="p-3">Annotation / Label</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-zinc-900 font-mono text-zinc-300">
                            {fileDetails.edges.length === 0 ? (
                              <tr>
                                <td colSpan={4} className="p-4 text-center text-zinc-500">No cross-symbol relationships detected.</td>
                              </tr>
                            ) : (
                              fileDetails.edges.map((edge, idx) => (
                                <tr key={`${edge.source}-${edge.target}-${idx}`} className="hover:bg-zinc-900/40 text-[11px]">
                                  <td className="p-3 text-zinc-400 break-all">{edge.source}</td>
                                  <td className="p-3">
                                    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold ${
                                      edge.type === 'AST' ? 'bg-blue-950/40 text-blue-400 border border-blue-900/20' :
                                      edge.type === 'CFG' ? 'bg-orange-950/40 text-orange-400 border border-orange-900/20' :
                                      edge.type === 'DFG' ? 'bg-purple-950/40 text-purple-400 border border-purple-900/20' :
                                      edge.type === 'CALLS' ? 'bg-pink-950/40 text-pink-400 border border-pink-900/20' :
                                      'bg-teal-950/40 text-teal-400 border border-teal-900/20'
                                    }`}>
                                      {edge.type}
                                    </span>
                                  </td>
                                  <td className="p-3 text-white break-all">{edge.target}</td>
                                  <td className="p-3 text-zinc-500">{edge.label || '-'}</td>
                                </tr>
                              ))
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="h-full flex items-center justify-center text-zinc-500 text-xs">
                  Failed to load graph records.
                </div>
              )}
            </div>
          </div>
        ) : (
          /* CPG Database Dashboard Overview - Renders when no file is selected */
          <div className="flex-1 flex flex-col p-8 overflow-y-auto bg-zinc-950 select-text">
            {isLoadingStats ? (
              <div className="flex-1 flex flex-col items-center justify-center text-zinc-500 space-y-2 text-xs">
                <Loader2 className="w-6 h-6 animate-spin text-zinc-400" />
                <span>Loading database statistics...</span>
              </div>
            ) : dbStats ? (
              <div className="space-y-8 max-w-4xl">
                {/* Dashboard Header */}
                <div>
                  <h2 className="text-xl font-bold tracking-tight text-white flex items-center space-x-2">
                    <Database className="w-5 h-5 text-purple-400" />
                    <span>CPG Database Dashboard</span>
                  </h2>
                  <p className="text-xs text-zinc-505 mt-1">
                    Compiled metrics, symbol types, and relations currently stored inside centralized SQLite index.
                  </p>
                </div>

                {/* Big Cards */}
                <div className="grid grid-cols-3 gap-4 font-sans">
                  <div className="p-4 rounded-xl border border-zinc-900 bg-zinc-900/10">
                    <div className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider">Indexed Nodes (Symbols)</div>
                    <div className="text-2xl font-bold text-white mt-1">{dbStats.total_symbols.toLocaleString()}</div>
                    <div className="text-[10px] text-zinc-550 mt-1">Variables, Functions, Classes, Tables</div>
                  </div>
                  <div className="p-4 rounded-xl border border-zinc-900 bg-zinc-900/10">
                    <div className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider">CPG Graph Edges</div>
                    <div className="text-2xl font-bold text-white mt-1">{dbStats.total_edges.toLocaleString()}</div>
                    <div className="text-[10px] text-zinc-550 mt-1">AST, DFG, CFG, CALLS, DATA_ACCESS</div>
                  </div>
                  <div className="p-4 rounded-xl border border-zinc-900 bg-zinc-900/10 flex flex-col justify-between">
                    <div>
                      <div className="text-[10px] text-zinc-500 font-semibold uppercase tracking-wider">Centralized Folder</div>
                      <div className="text-xs font-semibold text-emerald-400 truncate mt-1">graph.db</div>
                    </div>
                    <div className="text-[9px] font-mono text-zinc-650 truncate max-w-full">Dir: {globalDbPath}</div>
                  </div>
                </div>

                {/* Confidence Card */}
                {dbStats.confidence_summary && (
                  <ConfidenceCard
                    highCount={dbStats.confidence_summary.high}
                    mediumCount={dbStats.confidence_summary.medium}
                    lowCount={dbStats.confidence_summary.low}
                    totalCount={
                      dbStats.confidence_summary.high +
                      dbStats.confidence_summary.medium +
                      dbStats.confidence_summary.low
                    }
                  />
                )}

                {/* Grid for Nodes and Edges breakdown */}
                <div className="grid grid-cols-2 gap-6">
                  {/* Symbols Kind Breakdown */}
                  <div className="space-y-3">
                    <h3 className="text-xs font-semibold text-zinc-400 flex items-center space-x-1.5">
                      <Cpu className="w-3.5 h-3.5 text-zinc-500" />
                      <span>Node Type Distribution</span>
                    </h3>
                    <div className="border border-zinc-900 bg-zinc-900/5 rounded-xl p-4 divide-y divide-zinc-900 text-xs">
                      {Object.keys(dbStats.symbols_summary).length === 0 ? (
                        <div className="text-zinc-600 text-center py-2">No symbols mapped.</div>
                      ) : (
                        Object.entries(dbStats.symbols_summary).map(([kind, count]) => (
                          <div key={kind} className="flex justify-between py-2 first:pt-0 last:pb-0 font-sans">
                            <span className="font-mono text-zinc-400">{kind}</span>
                            <span className="font-bold text-white">{count}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  {/* Edges Type Breakdown */}
                  <div className="space-y-3">
                    <h3 className="text-xs font-semibold text-zinc-400 flex items-center space-x-1.5">
                      <Network className="w-3.5 h-3.5 text-zinc-500" />
                      <span>Graph Edge Mappings</span>
                    </h3>
                    <div className="border border-zinc-900 bg-zinc-900/5 rounded-xl p-4 divide-y divide-zinc-900 text-xs">
                      {Object.keys(dbStats.edges_summary).length === 0 ? (
                        <div className="text-zinc-600 text-center py-2">No relationship edges resolved.</div>
                      ) : (
                        Object.entries(dbStats.edges_summary).map(([etype, count]) => (
                          <div key={etype} className="flex justify-between py-2 first:pt-0 last:pb-0 font-sans">
                            <span className="font-mono text-zinc-400">{etype}</span>
                            <span className="font-bold text-white">{count}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>

                {/* SQL tables list */}
                {dbStats.sql_tables.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-xs font-semibold text-zinc-400 flex items-center space-x-1.5">
                      <HardDrive className="w-3.5 h-3.5 text-zinc-500" />
                      <span>Discovered Database Tables ({dbStats.sql_tables.length})</span>
                    </h3>
                    <div className="grid grid-cols-3 gap-2 text-xs font-mono">
                      {dbStats.sql_tables.map((table) => (
                        <div 
                          key={table.id}
                          className="p-2 border border-zinc-900 bg-zinc-950 rounded-lg text-zinc-350 truncate"
                          title={table.id}
                        >
                          {table.name}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-center p-8">
                <Layers className="w-10 h-10 text-zinc-700 mb-4 animate-pulse" />
                <h3 className="text-sm font-semibold text-zinc-300">CPG Database Explorer</h3>
                <p className="text-xs text-zinc-600 mt-1 max-w-xs">
                  Select a source file from the workspace file explorer tree on the left to inspect its code and graph.
                </p>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

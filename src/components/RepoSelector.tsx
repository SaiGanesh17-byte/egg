import React, { useState, useEffect } from 'react';
import { Folder, Terminal, Cpu, CheckCircle2, Loader2, AlertCircle } from 'lucide-react';

interface ScanStats {
  total_files: number;
  indexed_files: number;
  skipped_files: number;
  node_count: number;
}

interface RepoSelectorProps {
  onScanStart?: () => void;
  onScanComplete: (repoPath: string) => void;
}

export const RepoSelector: React.FC<RepoSelectorProps> = ({ onScanStart, onScanComplete }) => {
  const [pathInput, setPathInput] = useState('');
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stats, setStats] = useState<ScanStats | null>(null);

  // Keyboard shortcut Ctrl+O / Cmd+O to focus input
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'o') {
        e.preventDefault();
        const input = document.getElementById('repo-path-input');
        input?.focus();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const triggerScan = async (targetPath: string) => {
    if (!targetPath.trim()) return;
    setIsScanning(true);
    if (onScanStart) onScanStart();
    setError(null);
    try {
      const globalDbPath = typeof window !== 'undefined' ? (localStorage.getItem('egg_global_db_path') || '') : '';
      const response = await fetch('http://localhost:8000/api/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          repo_path: targetPath,
          db_storage_path: globalDbPath
        }),
      });

      if (!response.ok) {
        const errData = await response.json();
        throw new Error(errData.detail || 'Failed to scan directory');
      }

      const data = await response.json();
      setStats({
        total_files: data.total_files,
        indexed_files: data.indexed_files,
        skipped_files: data.skipped_files,
        node_count: data.node_count,
      });
      onScanComplete(targetPath);
    } catch (err: any) {
      console.error("CPG scan fetch error:", err);
      const isFetchErr = err instanceof TypeError || (err.message && err.message.includes('fetch'));
      setError(
        isFetchErr 
          ? "Failed to connect to backend. Please ensure the FastAPI server is running on http://localhost:8000/ (run: .venv/bin/uvicorn egg.server.app:app --port 8000)"
          : (err.message || 'An error occurred during indexing')
      );
      setStats(null);
    } finally {
      setIsScanning(false);
    }
  };

  const handleDirectoryPicker = async () => {
    try {
      setError(null);
      if (typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window) {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const selected = await open({
          directory: true,
          multiple: false,
          title: "Select Repository Directory"
        });
        if (selected && typeof selected === 'string') {
          setPathInput(selected);
          await triggerScan(selected);
        }
      } else if ('showDirectoryPicker' in window) {
        const handle = await (window as any).showDirectoryPicker();
        const guessedPath = `/Users/saiganeshongolu/${handle.name}`;
        setPathInput(guessedPath);
        await triggerScan(guessedPath);
      } else {
        alert('Directory Picker API is not supported in this browser. Please use Direct Path Input.');
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        console.error("Directory picker selection error:", err);
        setError(
          err.message 
            ? `Folder selection failed: ${err.message}` 
            : 'Failed to select directory. If this was a backend call issue, ensure the FastAPI server is running.'
        );
      }
    }
  };

  return (
    <div className="w-full max-w-xl mx-auto p-6 rounded-2xl border border-zinc-800 bg-zinc-950/70 backdrop-blur-xl shadow-2xl text-zinc-100 font-sans">
      <div className="flex items-center space-x-3 mb-6">
        <div className="p-2 bg-zinc-900 border border-zinc-800 rounded-lg">
          <Folder className="w-6 h-6 text-zinc-400" />
        </div>
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-white">Repository Ingestion</h2>
          <p className="text-xs text-zinc-400">Deterministic Code Property Graph (CPG) Builder</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Input Mode A: Direct Path Input */}
        <div>
          <label htmlFor="repo-path-input" className="block text-xs font-medium text-zinc-400 mb-1.5">
            Direct Local Directory Path
          </label>
          <div className="relative flex items-center">
            <input
              id="repo-path-input"
              type="text"
              placeholder="e.g. /Users/username/projects/egg"
              value={pathInput}
              onChange={(e) => setPathInput(e.target.value)}
              className="w-full px-4 py-2.5 bg-zinc-900/50 backdrop-blur-md border border-zinc-800 rounded-lg focus:outline-none focus:ring-1 focus:ring-zinc-600 focus:border-zinc-700 text-sm placeholder-zinc-600 font-mono text-zinc-100"
            />
            <div className="absolute right-3 flex items-center space-x-1.5 pointer-events-none">
              <kbd className="px-1.5 py-0.5 text-[10px] bg-zinc-800 border border-zinc-700 rounded text-zinc-400 font-mono shadow-sm">
                ⌘O
              </kbd>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="grid grid-cols-2 gap-3 pt-1">
          <button
            onClick={() => triggerScan(pathInput)}
            disabled={isScanning || !pathInput.trim()}
            className="flex items-center justify-center space-x-2 py-2.5 px-4 bg-white hover:bg-zinc-200 disabled:bg-zinc-800 disabled:text-zinc-600 text-black text-sm font-medium rounded-lg transition-all duration-150 shadow-sm"
          >
            {isScanning ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Indexing...</span>
              </>
            ) : (
              <>
                <Terminal className="w-4 h-4" />
                <span>Index Path</span>
              </>
            )}
          </button>

          {/* Input Mode B: Native Folder Picker */}
          <button
            onClick={handleDirectoryPicker}
            disabled={isScanning}
            className="flex items-center justify-center space-x-2 py-2.5 px-4 bg-zinc-900 hover:bg-zinc-800 border border-zinc-800 text-zinc-300 text-sm font-medium rounded-lg transition-all duration-150"
          >
            <Folder className="w-4 h-4 text-zinc-400" />
            <span>Select Folder</span>
          </button>
        </div>

        {/* Status Messages */}
        {error && (
          <div className="flex items-start space-x-2.5 p-3 rounded-lg border border-red-950/40 bg-red-950/20 text-red-400 text-xs">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {stats && (
          <div className="space-y-3 pt-2">
            {/* CPG Status Pill */}
            <div className="flex items-center justify-between p-3 rounded-lg border border-zinc-800 bg-zinc-900/30">
              <div className="flex items-center space-x-2">
                <Cpu className="w-4 h-4 text-emerald-500" />
                <span className="text-xs font-medium text-zinc-300">CPG Status</span>
              </div>
              <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-medium bg-emerald-950/40 text-emerald-400 border border-emerald-900/30 rounded-full">
                4 Layers Indexed | {stats.node_count.toLocaleString()} Nodes
              </span>
            </div>

            {/* Scan Stats Details */}
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="p-2 rounded-lg border border-zinc-900 bg-zinc-950/40">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Discovered</div>
                <div className="text-base font-semibold text-zinc-200 mt-0.5">{stats.total_files}</div>
              </div>
              <div className="p-2 rounded-lg border border-zinc-900 bg-zinc-950/40">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Indexed</div>
                <div className="text-base font-semibold text-zinc-200 mt-0.5">{stats.indexed_files}</div>
              </div>
              <div className="p-2 rounded-lg border border-zinc-900 bg-zinc-950/40">
                <div className="text-[10px] text-zinc-500 uppercase tracking-wider">Skipped</div>
                <div className="text-base font-semibold text-zinc-200 mt-0.5">{stats.skipped_files}</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

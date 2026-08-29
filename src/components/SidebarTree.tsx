import React, { useState } from 'react';
import { Folder, FolderOpen, FileCode, FileCode2, Database, ChevronRight, ChevronDown } from 'lucide-react';

export interface FileTreeNode {
  name: string;
  path: string;
  type: 'file' | 'directory';
  children?: FileTreeNode[];
}

interface SidebarTreeProps {
  tree: FileTreeNode[];
  onFileSelect?: (filePath: string) => void;
  selectedFilePath?: string | null;
}

const TreeNode: React.FC<{
  node: FileTreeNode;
  depth: number;
  onFileSelect?: (filePath: string) => void;
  selectedFilePath?: string | null;
}> = ({ node, depth, onFileSelect, selectedFilePath }) => {
  const [isOpen, setIsOpen] = useState(false);
  const isSelected = selectedFilePath === node.path;

  const handleToggle = () => {
    if (node.type === 'directory') {
      setIsOpen(!isOpen);
    } else if (onFileSelect) {
      onFileSelect(node.path);
    }
  };

  const renderFileIcon = () => {
    if (node.name.endsWith('.sql')) {
      return <Database className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />;
    }
    if (node.name.endsWith('.ts') || node.name.endsWith('.tsx')) {
      return <FileCode2 className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />;
    }
    return <FileCode className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />;
  };

  return (
    <div className="select-none font-sans">
      <div
        onClick={handleToggle}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
        className={`flex items-center justify-between py-1.5 pr-3 cursor-pointer text-xs transition-colors duration-150 rounded-md my-0.5 ${
          isSelected
            ? 'bg-zinc-800 text-white font-medium'
            : 'text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200'
        }`}
      >
        <div className="flex items-center space-x-2 truncate">
          {node.type === 'directory' ? (
            <>
              {isOpen ? (
                <FolderOpen className="w-3.5 h-3.5 text-zinc-400 flex-shrink-0" />
              ) : (
                <Folder className="w-3.5 h-3.5 text-zinc-500 flex-shrink-0" />
              )}
            </>
          ) : (
            renderFileIcon()
          )}
          <span className="truncate">{node.name}</span>
        </div>

        {node.type === 'directory' && (
          <span className="text-zinc-500 hover:text-zinc-300">
            {isOpen ? (
              <ChevronDown className="w-3.5 h-3.5" />
            ) : (
              <ChevronRight className="w-3.5 h-3.5" />
            )}
          </span>
        )}
      </div>

      {node.type === 'directory' && isOpen && node.children && (
        <div className="overflow-hidden transition-all duration-300">
          {node.children.map((child, idx) => (
            <TreeNode
              key={`${child.path}-${idx}`}
              node={child}
              depth={depth + 1}
              onFileSelect={onFileSelect}
              selectedFilePath={selectedFilePath}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const SidebarTree: React.FC<SidebarTreeProps> = ({
  tree,
  onFileSelect,
  selectedFilePath,
}) => {
  if (!tree || tree.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-xs text-zinc-550 font-sans">
        No files matching index parameters found.
      </div>
    );
  }

  return (
    <div className="w-full max-w-xs h-full bg-zinc-950/20 text-zinc-300 py-3 px-2 border-r border-zinc-900/60 overflow-y-auto">
      <div className="text-[10px] uppercase font-semibold tracking-wider text-zinc-500 px-2.5 mb-2.5">
        Files
      </div>
      <div className="space-y-0.5">
        {tree.map((node, idx) => (
          <TreeNode
            key={`${node.path}-${idx}`}
            node={node}
            depth={0}
            onFileSelect={onFileSelect}
            selectedFilePath={selectedFilePath}
          />
        ))}
      </div>
    </div>
  );
};

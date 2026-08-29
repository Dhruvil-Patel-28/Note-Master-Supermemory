"use client";

import { useState } from "react";
import { X, Download } from "lucide-react";
import { Artifact } from "@/lib/api";
import { Button } from "@/components/ui/button";

interface ArtifactPanelProps {
  artifact: Artifact;
  onClose: () => void;
}

export default function ArtifactPanel({ artifact, onClose }: ArtifactPanelProps) {
  const [downloading, setDownloading] = useState(false);

  const downloadFile = () => {
    setDownloading(true);
    const blob = new Blob([artifact.content], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${artifact.title.replace(/[^a-zA-Z0-9]/g, "_").toLowerCase()}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setTimeout(() => setDownloading(false), 1500);
  };

  return (
    <div className="flex h-full flex-col border-l bg-background">
      {/* Header */}
      <div className="flex items-center justify-between border-b px-3 py-2">
        <div className="flex items-center gap-2">
          <div className="flex size-6 items-center justify-center rounded bg-primary/10 text-primary">
            <span className="text-xs font-bold">H</span>
          </div>
          <span className="text-sm font-medium">{artifact.title}</span>
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={downloadFile}
            disabled={downloading}
            className="h-7 gap-1 px-2 text-xs"
          >
            <Download className="size-3" />
            {downloading ? "Saved" : "Download"}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-7 w-7"
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      {/* Preview */}
      <div className="min-h-0 flex-1">
        <iframe
          srcDoc={artifact.content}
          className="h-full w-full border-0"
          sandbox="allow-same-origin"
          title={artifact.title}
        />
      </div>
    </div>
  );
}

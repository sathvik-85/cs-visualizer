import { useState } from "react";

interface Props {
  code: string;
}

export function CodeViewer({ code }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-viewer">
      <div className="code-header">
        <span className="code-title">Generated Manim Code</span>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
      <pre className="code-block">
        <code>{code}</code>
      </pre>
    </div>
  );
}

import { useState } from "react";

const EXAMPLES = [
  "Binary Search",
  "Depth-First Search",
  "Hash Tables",
  "Binary Search Tree",
  "How TCP/IP works",
  "What is a CPU cache",
  "How does garbage collection work",
  "What is virtual memory",
  "How does DNS resolve a domain",
  "What is a mutex and deadlock",
];

interface Props {
  onSubmit: (topic: string) => void;
  disabled: boolean;
}

export function PromptInput({ onSubmit, disabled }: Props) {
  const [topic, setTopic] = useState("");

  const handleSubmit = () => {
    const t = topic.trim();
    if (t.length >= 3) onSubmit(t);
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="prompt-input">
      <textarea
        className="topic-textarea"
        placeholder="Describe a CS concept to visualize…&#10;e.g. &quot;Explain how merge sort works step by step&quot;"
        value={topic}
        onChange={(e) => setTopic(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled}
        rows={3}
      />
      <button
        className="generate-btn"
        onClick={handleSubmit}
        disabled={disabled || topic.trim().length < 3}
      >
        {disabled ? "Generating…" : "Generate Animation"}
      </button>
      <div className="examples">
        <span className="examples-label">Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            className="chip"
            onClick={() => {
              setTopic(ex);
              if (!disabled) onSubmit(ex);
            }}
            disabled={disabled}
          >
            {ex}
          </button>
        ))}
      </div>
    </div>
  );
}

export type FieldType = "text" | "textarea" | "number" | "checkbox";

export interface AgentField {
  name: string;
  label: string;
  type: FieldType;
  rows?: number;
  placeholder?: string;
}

export interface AgentConfig {
  slug: string;
  title: string;
  tagline: string;
  purpose: string;
  accent: string;
  features: string[];
  limitations: string[];
  fields: AgentField[];
  sample: Record<string, string | number | boolean>;
  repo: string;
}

export const agent: AgentConfig = {
  "slug": "plotxyz-code-review-agent",
  "title": "Code Review",
  "tagline": "A second pair of eyes for the risky parts.",
  "purpose": "Reviews Python source for correctness smells, long functions, high control-flow density, dynamic execution, shell injection, hardcoded credentials, and unsafe deserialization.",
  "accent": "#60a5fa",
  "features": [
    "AST metrics and findings",
    "Security pattern checks",
    "Actionable score and checklist"
  ],
  "limitations": [
    "Heuristics do not prove the absence of bugs or vulnerabilities.",
    "Only Python receives AST analysis."
  ],
  "fields": [
    {
      "name": "code",
      "label": "Source code",
      "type": "textarea",
      "rows": 10,
      "placeholder": ""
    },
    {
      "name": "language",
      "label": "Language (python or other)",
      "type": "text",
      "rows": 4,
      "placeholder": ""
    }
  ],
  "sample": {
    "code": "import subprocess\nAPI_KEY = \"sk-test-12345678\"\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n\ndef check(value):\n    if value == None:\n        return eval(value)\n    return value",
    "language": "python"
  },
  "repo": "https://github.com/sukhee-2626/plotxyz-code-review-agent"
};

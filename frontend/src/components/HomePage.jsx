const TOOL_CATALOG = [
  {
    id: 'api-tester',
    name: 'API Tester',
    icon: '🧪',
    description: 'Import a curl command, pick negative/boundary tests, and run them against a live API.',
    available: true,
  },
  {
    id: 'jmeter-report',
    name: 'JMeter Report Generator',
    icon: '📊',
    description: 'Generate an HTML dashboard report from a JMeter results CSV/JTL file.',
    available: true,
  },
  {
    id: 'karate-testcases',
    name: 'Karate Test Case Generator',
    icon: '🥋',
    description: 'Turn Karate HTML execution reports into an Excel sheet of API test cases, one step per request.',
    available: true,
  },
  {
    id: 'chain-tester',
    name: 'API Chain Tester',
    icon: '🔗',
    description: 'Chain multiple API calls together, passing data between them, then run mutation tests against the last one.',
    available: true,
  },
  {
    id: 'credential-tester',
    name: 'Expiring Credential Tester',
    icon: '🔐',
    description: 'Test an endpoint whose token/header expires mid-run — pauses and asks for a fresh value instead of failing every case after it.',
    available: true,
  },
  {
    id: 'test-case-creator',
    name: 'Test Case Creator',
    icon: '📝',
    description: 'Generate structured test cases from requirements or user stories.',
    available: false,
  },
  {
    id: 'test-data-generator',
    name: 'Test Data Generator',
    icon: '🧬',
    description: 'Generate realistic sample data for test fixtures.',
    available: false,
  },
];

export default function HomePage({ onSelectTool }) {
  return (
    <div className="home-page">
      <p className="home-intro">Pick a tool to get started. More tools will show up here over time.</p>
      <div className="tool-grid">
        {TOOL_CATALOG.map((tool) => (
          <button
            key={tool.id}
            type="button"
            className={`tool-card${tool.available ? '' : ' tool-card-disabled'}`}
            disabled={!tool.available}
            onClick={() => tool.available && onSelectTool(tool.id)}
          >
            <span className="tool-icon">{tool.icon}</span>
            <span className="tool-name">{tool.name}</span>
            <span className="tool-description">{tool.description}</span>
            {!tool.available && <span className="tool-badge">Coming soon</span>}
          </button>
        ))}
      </div>
    </div>
  );
}

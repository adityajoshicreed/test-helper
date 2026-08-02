import { useState } from 'react';
import HomePage from './components/HomePage';
import ApiTesterTool from './tools/ApiTesterTool';
import ChainTesterTool from './tools/ChainTesterTool';
import CredentialExpiryTester from './tools/CredentialExpiryTester';
import JmeterReportTool from './tools/JmeterReportTool';
import KarateTestCaseTool from './tools/KarateTestCaseTool';

const TOOLS = {
  'api-tester': { name: 'API Tester', component: ApiTesterTool },
  'jmeter-report': { name: 'JMeter Report Generator', component: JmeterReportTool },
  'karate-testcases': { name: 'Karate Test Case Generator', component: KarateTestCaseTool },
  'chain-tester': { name: 'API Chain Tester', component: ChainTesterTool },
  'credential-tester': { name: 'Expiring Credential Tester', component: CredentialExpiryTester },
};

export default function App() {
  const [activeTool, setActiveTool] = useState(null); // null = home page

  const tool = activeTool ? TOOLS[activeTool] : null;
  const ToolComponent = tool?.component;

  return (
    <div className="app-shell">
      <header className="app-header">
        <button className="brand" onClick={() => setActiveTool(null)}>
          <h1>QA Helper Tool</h1>
          {tool && <span className="breadcrumb-sep"> / {tool.name}</span>}
        </button>
        {tool && (
          <button className="back-button" onClick={() => setActiveTool(null)}>
            ← All tools
          </button>
        )}
      </header>

      <main>
        {!ToolComponent && <HomePage onSelectTool={setActiveTool} />}
        {ToolComponent && <ToolComponent />}
      </main>
    </div>
  );
}

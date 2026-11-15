#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const net = require('node:net');
const http = require('node:http');
const { spawn, spawnSync } = require('node:child_process');

const ROOT = path.resolve(__dirname, '..');
const CACHE = path.join(ROOT, '.dev-cache');
const WINDOWS = process.platform === 'win32';
const MAVEN_VERSION = '3.9.11';

function backendType(args) {
  if (args.length !== 1 || !['java', 'python'].includes(args[0].toLowerCase())) {
    throw new Error('Usage: node scripts/start.cjs <java|python>');
  }
  return args[0].toLowerCase();
}

function supportedNode(version) {
  const [major, minor] = version.split('.').map(Number);
  return (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major >= 24;
}

function findExecutable(name, env = process.env) {
  for (const directory of (env.PATH || env.Path || '').split(path.delimiter)) {
    if (!directory) continue;
    for (const suffix of WINDOWS ? ['', '.exe', '.cmd', '.bat'] : ['']) {
      const candidate = path.join(directory, name + suffix);
      try {
        fs.accessSync(candidate, WINDOWS ? fs.constants.F_OK : fs.constants.X_OK);
        if (fs.statSync(candidate).isFile()) return candidate;
      } catch { /* Try the next PATH entry. */ }
    }
  }
  return null;
}

function npmCli() {
  const directories = [path.dirname(process.execPath), ...(process.env.PATH || process.env.Path || '').split(path.delimiter)];
  const candidates = [];
  for (const dir of directories) {
    if (!dir) continue;
    candidates.push(path.join(dir, 'node_modules/npm/bin/npm-cli.js'));
    candidates.push(path.resolve(dir, '../lib/node_modules/npm/bin/npm-cli.js'));
    try {
      const resolved = fs.realpathSync(path.join(dir, 'npm'));
      if (resolved.endsWith('.js')) candidates.push(resolved);
    } catch { /* npm may only have a Windows .cmd launcher here. */ }
  }
  // Debian/Ubuntu package layout.
  candidates.push('/usr/share/nodejs/npm/bin/npm-cli.js');
  const found = candidates.find(candidate => fs.existsSync(candidate));
  if (!found) throw new Error('Cannot find npm. Install Node.js with npm and try again.');
  return found;
}

function probe(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8', windowsHide: true });
  if (result.error || result.status !== 0) return null;
  return `${result.stdout || ''}\n${result.stderr || ''}`.trim();
}

function javaTools(env = process.env) {
  const executable = name => {
    if (env.JAVA_HOME) return path.join(env.JAVA_HOME, 'bin', name + (WINDOWS ? '.exe' : ''));
    return findExecutable(name, env);
  };
  const java = executable('java');
  const javac = executable('javac');
  const javaVersion = java && probe(java, ['-version']);
  const javacVersion = javac && probe(javac, ['-version']);
  const runtime = javaVersion && javaVersion.match(/version\s+"(\d+)/);
  const compiler = javacVersion && javacVersion.match(/javac\s+(\d+)/);
  if (!runtime || Number(runtime[1]) < 21 || !compiler || Number(compiler[1]) < 21) {
    throw new Error('Install a Java 21+ JDK (including javac), and set JAVA_HOME to that JDK or add its bin directory to PATH.');
  }
  return { java, javac };
}

function pythonCommand() {
  const candidates = WINDOWS ? [['py', '-3.13'], ['py', '-3.12'], ['py', '-3'], ['python'], ['python3']] : [['python3.13'], ['python3.12'], ['python3'], ['python']];
  for (const [command, ...args] of candidates) {
    const executable = findExecutable(command);
    if (!executable) continue;
    if (probe(executable, [...args, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)']) !== null) {
      return [executable, ...args];
    }
  }
  throw new Error('Install Python 3.12+ with pip and venv support, then try again.');
}

function fingerprint(files, version = process.versions.node) {
  const hash = crypto.createHash('sha256');
  hash.update(`${process.platform}:${process.arch}:${version}`);
  for (const file of files) hash.update(fs.readFileSync(file));
  return hash.digest('hex');
}

function verifyChecksum(archive, checksumText) {
  const expected = checksumText.trim().split(/\s+/)[0].toLowerCase();
  const actual = crypto.createHash('sha512').update(fs.readFileSync(archive)).digest('hex');
  if (!/^[a-f0-9]{128}$/.test(expected) || expected !== actual) {
    throw new Error('Maven download checksum verification failed. The archive will not be used.');
  }
}

function escapeXml(value) {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

function mavenProxySettings(env = process.env) {
  const raw = env.HTTPS_PROXY || env.https_proxy || env.HTTP_PROXY || env.http_proxy;
  if (!raw) return '<settings/>\n';
  const proxy = new URL(raw.includes('://') ? raw : `http://${raw}`);
  if (proxy.username || proxy.password) {
    throw new Error('For an authenticated proxy, provide a secure Maven settings file through MAVEN_SETTINGS. Credentials are not copied into generated files.');
  }
  return `<settings><proxies><proxy><id>launcher</id><active>true</active><protocol>http</protocol><host>${escapeXml(proxy.hostname)}</host><port>${proxy.port || 80}</port><nonProxyHosts>localhost|127.0.0.1</nonProxyHosts></proxy></proxies></settings>\n`;
}

function availablePort(port) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once('error', error => reject(new Error(`Port ${port} is unavailable (${error.code}). Stop the existing service and try again.`)));
    server.listen(port, '127.0.0.1', () => server.close(resolve));
  });
}

function httpReady(port, endpoint, accepts) {
  return new Promise(resolve => {
    const request = http.get({ hostname: '127.0.0.1', port, path: endpoint, timeout: 1000 }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => {
        try { resolve(response.statusCode === 200 && accepts(body)); } catch { resolve(false); }
      });
      response.on('error', () => resolve(false));
    });
    request.on('timeout', () => request.destroy());
    request.on('error', () => resolve(false));
  });
}

class Launcher {
  constructor() {
    this.children = new Set();
    this.stopping = false;
  }

  child(command, args, cwd, env = process.env) {
    const child = spawn(command, args, { cwd, env, stdio: 'inherit', detached: !WINDOWS, windowsHide: true });
    this.children.add(child);
    child.done = new Promise(resolve => {
      child.once('error', error => { child.failure = error; resolve({ code: 1, error }); });
      child.once('exit', (code, signal) => resolve({ code, signal }));
    }).then(result => { this.children.delete(child); return result; });
    return child;
  }

  async command(command, args, cwd, env = process.env) {
    if (this.stopping) throw new Error('Startup cancelled.');
    const result = await this.child(command, args, cwd, env).done;
    if (result.code !== 0) throw new Error(`${path.basename(command)} failed${result.error ? `: ${result.error.message}` : ` (exit ${result.code ?? result.signal})`}.`);
  }

  async stop() {
    if (this.stopping) return;
    this.stopping = true;
    const children = [...this.children];
    for (const child of children) this.kill(child, false);
    let timer;
    await Promise.race([
      Promise.all(children.map(child => child.done)),
      new Promise(resolve => { timer = setTimeout(resolve, 4000); }),
    ]);
    clearTimeout(timer);
    for (const child of this.children) this.kill(child, true);
  }

  kill(child, force) {
    if (!child.pid || child.exitCode !== null || child.signalCode !== null) return;
    if (WINDOWS) {
      // Only terminate process trees spawned by this launcher.
      spawnSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore', windowsHide: true });
    } else {
      try { process.kill(-child.pid, force ? 'SIGKILL' : 'SIGTERM'); } catch { /* Already stopped. */ }
    }
  }

  async ready(child, port, endpoint, accepts) {
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline && !this.stopping) {
      if (child.failure || child.exitCode !== null || child.signalCode !== null) throw new Error(`Service on port ${port} exited before becoming ready.`);
      if (await httpReady(port, endpoint, accepts)) return;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw new Error(`Service on port ${port} did not become ready within 60 seconds.`);
  }

  async frontend(npm) {
    const directory = path.join(ROOT, 'frontend');
    const stamp = path.join(CACHE, 'frontend.sha256');
    const wanted = fingerprint([path.join(directory, 'package.json'), path.join(directory, 'package-lock.json')]);
    let current = '';
    try { current = fs.readFileSync(stamp, 'utf8'); } catch { /* First run. */ }
    if (current !== wanted || !fs.existsSync(path.join(directory, 'node_modules/vite/bin/vite.js'))) {
      console.log('\nInstalling frontend dependencies from the lockfile…');
      await this.command(process.execPath, [npm, 'ci', '--cache', path.join(CACHE, 'npm')], directory);
      fs.writeFileSync(stamp, wanted);
    }
  }

  async python() {
    const directory = path.join(ROOT, 'backend');
    const venv = path.join(directory, 'venv');
    const python = path.join(venv, WINDOWS ? 'Scripts/python.exe' : 'bin/python');
    if (!fs.existsSync(python)) {
      const [executable, ...args] = pythonCommand();
      console.log('\nCreating Python virtual environment…');
      await this.command(executable, [...args, '-m', 'venv', venv], directory);
    }
    if (probe(python, ['-c', 'import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)']) === null) {
      throw new Error('backend/venv is unusable or uses Python older than 3.12. Recreate it with Python 3.12+ and try again.');
    }
    console.log('\nPreparing Django dependencies and database…');
    const env = { ...process.env, PIP_CACHE_DIR: path.join(CACHE, 'pip') };
    await this.command(python, ['-m', 'pip', 'install', '-r', 'requirements.txt'], directory, env);
    await this.command(python, ['manage.py', 'migrate', '--noinput'], directory, env);
    return this.child(python, ['manage.py', 'runserver', '127.0.0.1:8000', '--noreload'], directory, env);
  }

  async java(tools) {
    const directory = path.join(ROOT, 'backend-java');
    const cache = path.join(directory, '.mvn', 'cache');
    const home = process.env.MAVEN_HOME || path.join(cache, `apache-maven-${MAVEN_VERSION}`);
    fs.mkdirSync(cache, { recursive: true });
    if (!fs.existsSync(path.join(home, 'boot'))) {
      if (process.env.MAVEN_HOME) throw new Error('MAVEN_HOME must point to an Apache Maven installation.');
      const curl = findExecutable(WINDOWS ? 'curl.exe' : 'curl');
      const tar = findExecutable(WINDOWS ? 'tar.exe' : 'tar');
      if (!curl || !tar) throw new Error('Install curl and tar, or set MAVEN_HOME to an existing Maven installation. Windows 10/11 and macOS normally include both tools.');
      console.log('\nDownloading and verifying Maven…');
      const url = `https://repo.maven.apache.org/maven2/org/apache/maven/apache-maven/${MAVEN_VERSION}/apache-maven-${MAVEN_VERSION}-bin.tar.gz`;
      const archive = path.join(cache, 'maven.tar.gz');
      const checksum = path.join(cache, 'maven.sha512');
      await this.command(curl, ['--fail', '--location', '--silent', '--show-error', url, '-o', archive], directory);
      await this.command(curl, ['--fail', '--location', '--silent', '--show-error', `${url}.sha512`, '-o', checksum], directory);
      verifyChecksum(archive, fs.readFileSync(checksum, 'utf8'));
      await this.command(tar, ['-xzf', archive, '-C', cache], directory);
    }
    const classworlds = fs.readdirSync(path.join(home, 'boot')).find(file => /^plexus-classworlds-.*\.jar$/.test(file));
    if (!classworlds) throw new Error('Maven installation is incomplete. Remove backend-java/.mvn/cache/apache-maven-3.9.11 and retry, or set MAVEN_HOME.');
    const settings = process.env.MAVEN_SETTINGS || path.join(CACHE, 'maven-settings.xml');
    if (!process.env.MAVEN_SETTINGS) fs.writeFileSync(settings, mavenProxySettings());
    const trust = !WINDOWS && fs.existsSync('/etc/ssl/certs/java/cacerts') ? ['-Djavax.net.ssl.trustStore=/etc/ssl/certs/java/cacerts'] : [];
    console.log('\nBuilding the Java backend…');
    // Invoke Maven's Java launcher directly, avoiding .cmd quoting and shell differences on Windows.
    await this.command(tools.java, [
      ...trust, '-classpath', path.join(home, 'boot', classworlds),
      `-Dclassworlds.conf=${path.join(home, 'bin', 'm2.conf')}`, `-Dmaven.home=${home}`,
      `-Dmaven.multiModuleProjectDirectory=${directory}`, 'org.codehaus.plexus.classworlds.launcher.Launcher',
      '--strict-checksums', '-s', settings, `-Dmaven.repo.local=${path.join(cache, 'repository')}`, '-DskipTests', 'package',
    ], directory);
    return this.child(tools.java, [...trust, '-jar', path.join(directory, 'target', 'qa-helper-backend-1.0.0.jar')], directory,
      { ...process.env, PORT: '8000', BIND_ADDRESS: '127.0.0.1' });
  }

  async start(backend) {
    if (!supportedNode(process.versions.node)) throw new Error('Vite requires Node.js 20.19+, 22.12+, or 24+. Install a supported Node.js release with npm.');
    const npm = npmCli();
    const tools = backend === 'java' ? javaTools() : null;
    await Promise.all([availablePort(8000), availablePort(5173)]);
    fs.mkdirSync(CACHE, { recursive: true });
    await this.frontend(npm);
    const server = backend === 'java' ? await this.java(tools) : await this.python();
    await this.ready(server, 8000, backend === 'java' ? '/api/health/' : '/api/imported-requests/', body => {
      const parsed = JSON.parse(body);
      return backend === 'java' ? parsed.backend === 'spring-boot' && parsed.status === 'ok' : Array.isArray(parsed);
    });
    console.log('\nBackend is ready. Starting the frontend…');
    const frontend = this.child(process.execPath,
      [path.join(ROOT, 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
      path.join(ROOT, 'frontend'));
    await this.ready(frontend, 5173, '/', body => body.includes('id="root"'));
    console.log(`\nBoth services are ready (${backend} backend). Press Ctrl+C to stop both.`);
    const result = await Promise.race([server.done, frontend.done]);
    if (!this.stopping) throw new Error(`A service exited unexpectedly (exit ${result.code ?? result.signal}); stopping both services.`);
  }
}

async function main() {
  let launcher;
  try {
    const backend = backendType(process.argv.slice(2));
    launcher = new Launcher();
    const signal = async () => { await launcher.stop(); process.exit(130); };
    process.once('SIGINT', signal);
    process.once('SIGTERM', signal);
    await launcher.start(backend);
  } catch (error) {
    if (!launcher?.stopping) console.error(`\nStartup failed: ${error.message}`);
    process.exitCode = 1;
  } finally {
    if (launcher) await launcher.stop();
  }
}

module.exports = { backendType, supportedNode, fingerprint, verifyChecksum, mavenProxySettings, availablePort, httpReady, Launcher };
if (require.main === module) main();

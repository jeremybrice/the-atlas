# Dashboard UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a single-file web dashboard served by the aiohttp daemon that visualizes all ATLAS agent state and controls.

**Architecture:** One HTML file (`src/atlas/integrations/dashboard_ui.html`) using Alpine.js + Tailwind CSS via CDN. Served by a new `GET /` route in `DashboardServer`. Auto-polls API endpoints for live data. All interactive controls (goal submit, pause/resume/kill, trust accept/dismiss, rule add/remove) use `fetch()` to existing API endpoints.

**Tech Stack:** Alpine.js 3.x (CDN), Tailwind CSS 3.x (CDN), JetBrains Mono font (CDN), vanilla `fetch()` for API calls.

---

### Task 1: Serve HTML route

**Files:**
- Modify: `src/atlas/integrations/dashboard.py:46-81`
- Test: `tests/unit/integrations/test_dashboard.py`

**Step 1: Write the failing test**

Add to `tests/unit/integrations/test_dashboard.py`:

```python
async def test_root_serves_html(full_dashboard, aiohttp_client):
    server, _, _, _ = full_dashboard
    app = server.create_app()
    client = await aiohttp_client(app)

    resp = await client.get("/")
    assert resp.status == 200
    assert resp.content_type == "text/html"
    body = await resp.text()
    assert "ATLAS" in body
    assert "alpine" in body.lower() or "x-data" in body.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/integrations/test_dashboard.py::test_root_serves_html -v`
Expected: FAIL (no route for `/`)

**Step 3: Write minimal implementation**

In `dashboard.py`, add to `create_app()` method at line 48 (after `app = web.Application()`):

```python
app.router.add_get("/", self._serve_ui)
```

Add the handler method to `DashboardServer`:

```python
async def _serve_ui(self, request: web.Request) -> web.Response:
    import importlib.resources as pkg_resources
    html_path = pkg_resources.files("atlas.integrations").joinpath("dashboard_ui.html")
    html = html_path.read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html")
```

Create a minimal placeholder `src/atlas/integrations/dashboard_ui.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ATLAS Dashboard</title>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0a0a0a] text-[#e0e0e0] font-mono" x-data="dashboard()">
    <div class="p-4">ATLAS Dashboard — placeholder</div>
    <script>
    function dashboard() { return {} }
    </script>
</body>
</html>
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/integrations/test_dashboard.py::test_root_serves_html -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All 317+ tests pass (no regressions)

**Step 6: Commit**

```bash
git add src/atlas/integrations/dashboard.py src/atlas/integrations/dashboard_ui.html tests/unit/integrations/test_dashboard.py
git commit -m "feat: add GET / route to serve dashboard UI placeholder"
```

---

### Task 2: Status bar — state, uptime, health indicators

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Build the status bar Alpine.js component**

Replace the placeholder HTML with the full page shell. The `dashboard()` function initializes Alpine state and starts polling:

```javascript
function dashboard() {
    return {
        // Status bar state
        status: { status: 'connecting', uptime_seconds: 0, paused: false, active_task_id: null, standing_rules_count: 0 },
        health: { database: 'unknown', skill_registry: 'unknown', memory: 'unknown', emergency: 'unknown' },
        activeTab: 'missions',
        statusError: false,

        // Polling
        statusInterval: null,
        tabInterval: null,

        init() {
            this.pollStatus();
            this.statusInterval = setInterval(() => this.pollStatus(), 3000);
            this.$watch('activeTab', () => { this.pollTab(); this.resetTabPolling(); });
            this.resetTabPolling();
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) { clearInterval(this.statusInterval); clearInterval(this.tabInterval); }
                else { this.pollStatus(); this.statusInterval = setInterval(() => this.pollStatus(), 3000); this.resetTabPolling(); }
            });
        },

        resetTabPolling() {
            clearInterval(this.tabInterval);
            this.tabInterval = setInterval(() => this.pollTab(), 5000);
        },

        async pollStatus() {
            try {
                const [statusRes, healthRes] = await Promise.all([fetch('/api/status'), fetch('/api/health')]);
                this.status = await statusRes.json();
                this.health = await healthRes.json();
                this.statusError = false;
            } catch (e) { this.statusError = true; }
        },

        async pollTab() { /* filled in Task 3+ */ },

        formatUptime(s) {
            const h = Math.floor(s / 3600); const m = Math.floor((s % 3600) / 60); const sec = Math.floor(s % 60);
            return h > 0 ? `${h}h ${m}m ${sec}s` : m > 0 ? `${m}m ${sec}s` : `${sec}s`;
        },

        healthColor(val) {
            if (!val) return '#666';
            if (val.startsWith('ok')) return '#00ff88';
            if (val === 'paused') return '#ffaa00';
            return '#ff4444';
        },
    }
}
```

Status bar HTML:

```html
<!-- Status Bar -->
<div class="border-b border-[#1a1a1a] bg-[#141414] px-4 py-3 space-y-2">
    <!-- Row 1: State -->
    <div class="flex items-center gap-4 text-sm">
        <span class="flex items-center gap-2">
            <span class="w-2 h-2 rounded-full" :class="statusError ? 'bg-red-500' : status.paused ? 'bg-amber-400' : 'bg-green-400'"></span>
            <span x-text="statusError ? 'Disconnected' : status.paused ? 'Paused' : 'Running'" class="font-bold"></span>
        </span>
        <span class="text-[#666]">|</span>
        <span>Uptime: <span x-text="formatUptime(status.uptime_seconds)" class="text-[#00ff88]"></span></span>
        <span class="text-[#666]">|</span>
        <span>Task: <span x-text="status.active_task_id || 'Idle'" :class="status.active_task_id ? 'text-amber-400' : 'text-[#666]'"></span></span>
    </div>
    <!-- Row 2: Health -->
    <div class="flex items-center gap-4 text-xs">
        <template x-for="key in ['database', 'skill_registry', 'memory', 'emergency']">
            <span class="flex items-center gap-1">
                <span class="w-1.5 h-1.5 rounded-full" :style="'background:' + healthColor(health[key])"></span>
                <span x-text="key.replace('_', ' ')" class="capitalize text-[#999]"></span>
            </span>
        </template>
    </div>
</div>
```

**Step 2: Verify manually**

Run daemon and open browser:
```bash
atlas daemon start  # with webhook + dashboard enabled
open http://localhost:8484/
```
Expected: Status bar shows "Running", uptime counting, 4 health dots (green if daemon healthy).

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): status bar with state, uptime, health indicators"
```

---

### Task 3: Status bar — goal input and emergency controls

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add goal submission and control buttons**

Add to Alpine state:

```javascript
goalText: '',
goalFeedback: '',
controlFeedback: '',

async submitGoal() {
    if (!this.goalText.trim()) return;
    try {
        const res = await fetch('/api/goal', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({goal_text: this.goalText}) });
        const data = await res.json();
        this.goalFeedback = res.ok ? 'Goal submitted' : (data.message || data.error || 'Error');
        if (res.ok) this.goalText = '';
    } catch (e) { this.goalFeedback = 'Connection error'; }
    setTimeout(() => this.goalFeedback = '', 2000);
},

async emergencyAction(action, body) {
    try {
        const opts = { method: 'POST', headers: {'Content-Type': 'application/json'} };
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch('/api/emergency/' + action, opts);
        const data = await res.json();
        this.controlFeedback = data.status || (data.killed ? 'Task killed' : 'No active task');
    } catch (e) { this.controlFeedback = 'Error'; }
    setTimeout(() => this.controlFeedback = '', 2000);
    this.pollStatus();
},

async killTask() {
    const taskId = prompt('Enter task ID to kill:');
    if (taskId) this.emergencyAction('kill', { task_id: taskId });
},
```

Add HTML row 3 inside the status bar div:

```html
<!-- Row 3: Controls -->
<div class="flex items-center gap-3 text-sm">
    <input x-model="goalText" @keydown.enter="submitGoal()" type="text" placeholder="Enter goal..."
        class="bg-[#0a0a0a] border border-[#333] rounded px-3 py-1 flex-1 text-[#e0e0e0] placeholder-[#555] focus:border-[#00ff88] focus:outline-none" />
    <button @click="submitGoal()" class="bg-[#00ff88] text-black px-3 py-1 rounded text-xs font-bold hover:bg-[#00cc66]">Execute</button>
    <span class="text-[#666]">|</span>
    <button @click="emergencyAction('pause')" class="border border-amber-500 text-amber-400 px-2 py-1 rounded text-xs hover:bg-amber-500/10">Pause</button>
    <button @click="emergencyAction('resume')" class="border border-green-500 text-green-400 px-2 py-1 rounded text-xs hover:bg-green-500/10">Resume</button>
    <button @click="killTask()" class="border border-red-500 text-red-400 px-2 py-1 rounded text-xs hover:bg-red-500/10">Kill Task</button>
    <span x-show="goalFeedback" x-text="goalFeedback" class="text-xs text-[#00ff88]" x-transition></span>
    <span x-show="controlFeedback" x-text="controlFeedback" class="text-xs text-amber-400" x-transition></span>
</div>
```

**Step 2: Verify manually**

Open `http://localhost:8484/`. Type a goal, press Execute. Press Pause/Resume. Verify feedback text appears and fades.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): goal input and emergency control buttons"
```

---

### Task 4: Tab navigation shell

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add tab bar and content container**

Add tab definitions to Alpine state:

```javascript
tabs: [
    { id: 'missions', label: 'Missions' },
    { id: 'skills', label: 'Skills' },
    { id: 'trust', label: 'Trust' },
    { id: 'rules', label: 'Rules' },
    { id: 'audit', label: 'Audit' },
    { id: 'memory', label: 'Memory' },
    { id: 'connectors', label: 'Connectors' },
    { id: 'config', label: 'Config' },
],
```

HTML below the status bar:

```html
<!-- Tabs -->
<div class="border-b border-[#1a1a1a] bg-[#111] px-4 flex gap-1 overflow-x-auto">
    <template x-for="tab in tabs">
        <button @click="activeTab = tab.id"
            :class="activeTab === tab.id ? 'text-[#00ff88] border-b-2 border-[#00ff88]' : 'text-[#666] hover:text-[#999]'"
            class="px-3 py-2 text-xs font-bold uppercase tracking-wider whitespace-nowrap transition-colors"
            x-text="tab.label">
        </button>
    </template>
</div>

<!-- Tab Content -->
<div class="p-4 overflow-y-auto" style="height: calc(100vh - 160px);">
    <!-- Each tab section will go here, shown/hidden with x-show -->
</div>
```

**Step 2: Verify manually**

Tabs render, clicking switches `activeTab`. Content area is empty but correctly sized.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): tab navigation bar"
```

---

### Task 5: Missions & Tasks tab

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add missions data and polling**

Add to Alpine state:

```javascript
missions: [],
tasks: {},
expandedMission: null,

async fetchMissions() {
    try {
        const res = await fetch('/api/missions');
        this.missions = await res.json();
    } catch (e) {}
},

async toggleMission(missionId) {
    if (this.expandedMission === missionId) { this.expandedMission = null; return; }
    this.expandedMission = missionId;
    try {
        const res = await fetch('/api/tasks?mission_id=' + missionId);
        this.tasks[missionId] = await res.json();
    } catch (e) {}
},

statusBadge(status) {
    const colors = { completed: 'bg-green-500/20 text-green-400', failed: 'bg-red-500/20 text-red-400', active: 'bg-amber-500/20 text-amber-400', executing: 'bg-amber-500/20 text-amber-400', pending: 'bg-[#333] text-[#999]', cancelled: 'bg-[#222] text-[#666]', planning: 'bg-blue-500/20 text-blue-400' };
    return colors[status] || 'bg-[#333] text-[#999]';
},
```

Update `pollTab()`:

```javascript
async pollTab() {
    if (this.activeTab === 'missions') await this.fetchMissions();
    // other tabs added in subsequent tasks
},
```

Also call `this.pollTab()` in `init()`.

HTML:

```html
<!-- Missions Tab -->
<div x-show="activeTab === 'missions'">
    <div class="space-y-1">
        <template x-for="m in missions" :key="m.mission_id">
            <div class="bg-[#141414] border border-[#1a1a1a] rounded">
                <div @click="toggleMission(m.mission_id)" class="flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[#1a1a1a]">
                    <div class="flex items-center gap-3 flex-1 min-w-0">
                        <span class="text-xs" x-text="expandedMission === m.mission_id ? '▼' : '▶'" class="text-[#666]"></span>
                        <span class="truncate" x-text="m.goal_text"></span>
                    </div>
                    <div class="flex items-center gap-3 flex-shrink-0">
                        <span :class="statusBadge(m.status)" class="px-2 py-0.5 rounded text-xs" x-text="m.status"></span>
                        <span class="text-xs text-[#666]" x-text="new Date(m.created_at).toLocaleString()"></span>
                    </div>
                </div>
                <div x-show="expandedMission === m.mission_id" class="border-t border-[#1a1a1a] px-4 py-2">
                    <template x-for="t in (tasks[m.mission_id] || [])" :key="t.task_id">
                        <div class="flex items-center justify-between py-1 text-sm">
                            <div class="flex items-center gap-2">
                                <span class="text-[#555]">├</span>
                                <span x-text="t.description" class="truncate"></span>
                            </div>
                            <div class="flex items-center gap-2">
                                <span class="text-xs text-[#666]" x-text="t.skill_id"></span>
                                <span :class="statusBadge(t.status)" class="px-2 py-0.5 rounded text-xs" x-text="t.status"></span>
                            </div>
                        </div>
                    </template>
                    <div x-show="!tasks[m.mission_id] || tasks[m.mission_id].length === 0" class="text-xs text-[#555] py-1">No tasks</div>
                </div>
            </div>
        </template>
        <div x-show="missions.length === 0" class="text-[#555] text-sm py-8 text-center">No missions yet</div>
    </div>
</div>
```

**Step 2: Verify manually**

With some missions in the database, open dashboard. Missions should list with status badges. Click to expand and see tasks.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): missions & tasks tab with expandable rows"
```

---

### Task 6: Skills tab

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add skills data and tab content**

Add to Alpine state:

```javascript
skills: [],

async fetchSkills() {
    try { const res = await fetch('/api/skills'); this.skills = await res.json(); } catch (e) {}
},

riskColor(level) {
    const colors = { low: 'bg-green-500/20 text-green-400', medium: 'bg-amber-500/20 text-amber-400', high: 'bg-orange-500/20 text-orange-400', critical: 'bg-red-500/20 text-red-400' };
    return colors[level] || 'bg-[#333] text-[#999]';
},
```

Update `pollTab()` to add: `if (this.activeTab === 'skills') await this.fetchSkills();`

HTML:

```html
<!-- Skills Tab -->
<div x-show="activeTab === 'skills'">
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <template x-for="s in skills" :key="s.skill_id">
            <div class="bg-[#141414] border border-[#1a1a1a] rounded p-4">
                <div class="flex items-center justify-between mb-2">
                    <span class="text-[#00ff88] font-bold text-sm" x-text="s.skill_id"></span>
                    <span :class="riskColor(s.risk_level)" class="px-2 py-0.5 rounded text-xs" x-text="s.risk_level"></span>
                </div>
                <p class="text-xs text-[#999] mb-2" x-text="s.description"></p>
                <div class="flex flex-wrap gap-1">
                    <template x-for="tag in s.tags">
                        <span class="bg-[#1a1a1a] text-[#666] px-2 py-0.5 rounded text-xs" x-text="tag"></span>
                    </template>
                </div>
            </div>
        </template>
    </div>
</div>
```

**Step 2: Verify manually**

Skills tab shows card grid with skill IDs, descriptions, risk badges, tags.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): skills tab with card grid"
```

---

### Task 7: Trust & Autonomy tab

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add trust data, recommendations, and actions**

Add to Alpine state:

```javascript
trustRecords: [],
trustRecommendations: [],
trustFeedback: '',

async fetchTrust() {
    try {
        const [recRes, trustRes] = await Promise.all([
            fetch('/api/trust/recommendations?status=pending'),
            fetch('/api/trust/records')
        ]);
        this.trustRecommendations = await recRes.json();
        this.trustRecords = await trustRes.json();
    } catch (e) {}
},

async trustAction(id, action) {
    try {
        await fetch('/api/trust/recommendations/' + id + '/' + action, { method: 'POST' });
        this.trustFeedback = action === 'accept' ? 'Accepted' : 'Dismissed';
        this.fetchTrust();
    } catch (e) { this.trustFeedback = 'Error'; }
    setTimeout(() => this.trustFeedback = '', 2000);
},

successRate(rec) {
    const total = rec.successes + rec.failures;
    return total > 0 ? Math.round((rec.successes / total) * 100) + '%' : 'N/A';
},
```

Update `pollTab()`: `if (this.activeTab === 'trust') await this.fetchTrust();`

HTML:

```html
<!-- Trust Tab -->
<div x-show="activeTab === 'trust'" class="space-y-6">
    <!-- Pending Recommendations -->
    <div>
        <h3 class="text-xs uppercase tracking-wider text-[#666] mb-3">Pending Recommendations <span x-show="trustFeedback" x-text="trustFeedback" class="text-[#00ff88] normal-case" x-transition></span></h3>
        <div class="space-y-2">
            <template x-for="r in trustRecommendations" :key="r.recommendation_id">
                <div class="bg-[#141414] border border-[#1a1a1a] rounded p-4 flex items-center justify-between">
                    <div>
                        <span class="text-[#00ff88] font-bold" x-text="r.skill_id"></span>
                        <span class="mx-2 text-[#555]">→</span>
                        <span :class="r.direction === 'escalate' ? 'text-green-400' : 'text-red-400'" x-text="r.direction"></span>
                        <span class="text-[#666] text-xs ml-2" x-text="r.current_level + ' → ' + r.recommended_level"></span>
                    </div>
                    <div class="flex gap-2">
                        <button @click="trustAction(r.recommendation_id, 'accept')" class="bg-green-500/20 text-green-400 px-3 py-1 rounded text-xs hover:bg-green-500/30">Accept</button>
                        <button @click="trustAction(r.recommendation_id, 'dismiss')" class="bg-[#333] text-[#999] px-3 py-1 rounded text-xs hover:bg-[#444]">Dismiss</button>
                    </div>
                </div>
            </template>
            <div x-show="trustRecommendations.length === 0" class="text-[#555] text-sm">No pending recommendations</div>
        </div>
    </div>
    <!-- Trust Records Table -->
    <div>
        <h3 class="text-xs uppercase tracking-wider text-[#666] mb-3">Trust Records</h3>
        <div class="bg-[#141414] border border-[#1a1a1a] rounded overflow-hidden">
            <table class="w-full text-sm">
                <thead><tr class="text-[#666] text-xs uppercase border-b border-[#1a1a1a]">
                    <th class="text-left px-4 py-2">Skill</th><th class="px-4 py-2">Successes</th><th class="px-4 py-2">Failures</th>
                    <th class="px-4 py-2">Rate</th><th class="px-4 py-2">Consec.</th><th class="px-4 py-2">Override</th><th class="px-4 py-2">Last</th>
                </tr></thead>
                <tbody>
                    <template x-for="r in trustRecords" :key="r.skill_id">
                        <tr class="border-b border-[#1a1a1a]/50 hover:bg-[#1a1a1a]">
                            <td class="px-4 py-2 text-[#00ff88]" x-text="r.skill_id"></td>
                            <td class="px-4 py-2 text-center text-green-400" x-text="r.successes"></td>
                            <td class="px-4 py-2 text-center text-red-400" x-text="r.failures"></td>
                            <td class="px-4 py-2 text-center" x-text="successRate(r)"></td>
                            <td class="px-4 py-2 text-center" x-text="r.consecutive_successes"></td>
                            <td class="px-4 py-2 text-center" x-text="r.autonomy_override ?? '—'"></td>
                            <td class="px-4 py-2 text-center" :class="r.last_outcome === 'success' ? 'text-green-400' : 'text-red-400'" x-text="r.last_outcome"></td>
                        </tr>
                    </template>
                </tbody>
            </table>
            <div x-show="trustRecords.length === 0" class="text-[#555] text-sm p-4 text-center">No trust records</div>
        </div>
    </div>
</div>
```

**Step 2: Verify manually**

Trust tab shows recommendations with accept/dismiss buttons and trust records table.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): trust & autonomy tab with recommendations and records"
```

---

### Task 8: Approval Rules tab

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add rules data, add form, and remove action**

Add to Alpine state:

```javascript
rules: [],
newRule: { match_skill: '*', match_risk: '*', decision: 'allow', description: '' },
ruleFeedback: '',

async fetchRules() {
    try { const res = await fetch('/api/approvals/rules'); this.rules = await res.json(); } catch (e) {}
},

async addRule() {
    try {
        const res = await fetch('/api/approvals/rules', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(this.newRule) });
        if (res.ok) { this.ruleFeedback = 'Rule added'; this.newRule = { match_skill: '*', match_risk: '*', decision: 'allow', description: '' }; this.fetchRules(); }
        else { this.ruleFeedback = 'Error'; }
    } catch (e) { this.ruleFeedback = 'Error'; }
    setTimeout(() => this.ruleFeedback = '', 2000);
},

async removeRule(ruleId) {
    try {
        await fetch('/api/approvals/rules/' + ruleId, { method: 'DELETE' });
        this.ruleFeedback = 'Rule removed';
        this.fetchRules();
    } catch (e) { this.ruleFeedback = 'Error'; }
    setTimeout(() => this.ruleFeedback = '', 2000);
},
```

Update `pollTab()`: `if (this.activeTab === 'rules') await this.fetchRules();`

HTML:

```html
<!-- Rules Tab -->
<div x-show="activeTab === 'rules'" class="space-y-4">
    <!-- Add Rule Form -->
    <div class="bg-[#141414] border border-[#1a1a1a] rounded p-4">
        <h3 class="text-xs uppercase tracking-wider text-[#666] mb-3">Add Rule <span x-show="ruleFeedback" x-text="ruleFeedback" class="text-[#00ff88] normal-case" x-transition></span></h3>
        <div class="flex gap-3 items-end flex-wrap">
            <div><label class="text-xs text-[#666] block mb-1">Skill Pattern</label><input x-model="newRule.match_skill" class="bg-[#0a0a0a] border border-[#333] rounded px-2 py-1 text-sm w-32" /></div>
            <div><label class="text-xs text-[#666] block mb-1">Risk</label>
                <select x-model="newRule.match_risk" class="bg-[#0a0a0a] border border-[#333] rounded px-2 py-1 text-sm">
                    <option value="*">*</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option>
                </select></div>
            <div><label class="text-xs text-[#666] block mb-1">Decision</label>
                <select x-model="newRule.decision" class="bg-[#0a0a0a] border border-[#333] rounded px-2 py-1 text-sm">
                    <option value="allow">allow</option><option value="deny">deny</option>
                </select></div>
            <div class="flex-1"><label class="text-xs text-[#666] block mb-1">Description</label><input x-model="newRule.description" class="bg-[#0a0a0a] border border-[#333] rounded px-2 py-1 text-sm w-full" /></div>
            <button @click="addRule()" class="bg-[#00ff88] text-black px-3 py-1 rounded text-xs font-bold hover:bg-[#00cc66]">Add</button>
        </div>
    </div>
    <!-- Rules Table -->
    <div class="bg-[#141414] border border-[#1a1a1a] rounded overflow-hidden">
        <table class="w-full text-sm">
            <thead><tr class="text-[#666] text-xs uppercase border-b border-[#1a1a1a]">
                <th class="text-left px-4 py-2">Skill</th><th class="px-4 py-2">Risk</th><th class="px-4 py-2">Decision</th><th class="text-left px-4 py-2">Description</th><th class="px-4 py-2"></th>
            </tr></thead>
            <tbody>
                <template x-for="r in rules" :key="r.rule_id">
                    <tr class="border-b border-[#1a1a1a]/50 hover:bg-[#1a1a1a]">
                        <td class="px-4 py-2 text-[#00ff88]" x-text="r.match_skill"></td>
                        <td class="px-4 py-2 text-center" x-text="r.match_risk"></td>
                        <td class="px-4 py-2 text-center"><span :class="r.decision === 'allow' ? 'text-green-400' : 'text-red-400'" x-text="r.decision"></span></td>
                        <td class="px-4 py-2 text-[#999]" x-text="r.description"></td>
                        <td class="px-4 py-2 text-center"><button @click="removeRule(r.rule_id)" class="text-red-400 hover:text-red-300 text-xs">Remove</button></td>
                    </tr>
                </template>
            </tbody>
        </table>
        <div x-show="rules.length === 0" class="text-[#555] text-sm p-4 text-center">No standing rules</div>
    </div>
</div>
```

**Step 2: Verify manually**

Rules tab shows form and table. Add/remove rules and verify they persist.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): approval rules tab with add/remove"
```

---

### Task 9: Audit Log tab

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add audit data and scrollable table**

Add to Alpine state:

```javascript
auditEntries: [],

async fetchAudit() {
    try { const res = await fetch('/api/audit?limit=100'); this.auditEntries = await res.json(); } catch (e) {}
},
```

Update `pollTab()`: `if (this.activeTab === 'audit') await this.fetchAudit();`

HTML:

```html
<!-- Audit Tab -->
<div x-show="activeTab === 'audit'">
    <div class="bg-[#141414] border border-[#1a1a1a] rounded overflow-hidden">
        <table class="w-full text-sm">
            <thead><tr class="text-[#666] text-xs uppercase border-b border-[#1a1a1a]">
                <th class="text-left px-4 py-2">Timestamp</th><th class="text-left px-4 py-2">Action</th><th class="text-left px-4 py-2">Actor</th><th class="px-4 py-2">Outcome</th><th class="text-left px-4 py-2">Mission</th>
            </tr></thead>
            <tbody>
                <template x-for="e in auditEntries" :key="e.entry_id">
                    <tr class="border-b border-[#1a1a1a]/50 hover:bg-[#1a1a1a]">
                        <td class="px-4 py-2 text-[#666] text-xs whitespace-nowrap" x-text="new Date(e.timestamp).toLocaleString()"></td>
                        <td class="px-4 py-2" x-text="e.action_type"></td>
                        <td class="px-4 py-2 text-[#999]" x-text="e.actor"></td>
                        <td class="px-4 py-2 text-center"><span :class="statusBadge(e.outcome)" class="px-2 py-0.5 rounded text-xs" x-text="e.outcome"></span></td>
                        <td class="px-4 py-2 text-[#555] text-xs" x-text="e.mission_id ? e.mission_id.substring(0, 8) + '...' : '—'"></td>
                    </tr>
                </template>
            </tbody>
        </table>
        <div x-show="auditEntries.length === 0" class="text-[#555] text-sm p-4 text-center">No audit entries</div>
    </div>
</div>
```

**Step 2: Verify manually**

Audit tab shows scrollable table of recent actions with timestamps and outcome badges.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): audit log tab"
```

---

### Task 10: Memory, Connectors, and Config tabs

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add remaining data fetchers**

Add to Alpine state:

```javascript
memoryStats: { episode_count: 0, mission_count: 0, embedding_count: 0 },
connectors: [],
configData: {},

async fetchMemory() {
    try { const res = await fetch('/api/memory/stats'); this.memoryStats = await res.json(); } catch (e) {}
},

async fetchConnectors() {
    try { const res = await fetch('/api/connectors'); this.connectors = await res.json(); } catch (e) {}
},

async fetchConfig() {
    try { const res = await fetch('/api/config'); this.configData = await res.json(); } catch (e) {}
},
```

Update `pollTab()` with remaining cases:

```javascript
async pollTab() {
    if (this.activeTab === 'missions') await this.fetchMissions();
    else if (this.activeTab === 'skills') await this.fetchSkills();
    else if (this.activeTab === 'trust') await this.fetchTrust();
    else if (this.activeTab === 'rules') await this.fetchRules();
    else if (this.activeTab === 'audit') await this.fetchAudit();
    else if (this.activeTab === 'memory') await this.fetchMemory();
    else if (this.activeTab === 'connectors') await this.fetchConnectors();
    else if (this.activeTab === 'config') await this.fetchConfig();
},
```

HTML for all three tabs:

```html
<!-- Memory Tab -->
<div x-show="activeTab === 'memory'">
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <template x-for="[label, key] in [['Episodes', 'episode_count'], ['Missions', 'mission_count'], ['Embeddings', 'embedding_count']]">
            <div class="bg-[#141414] border border-[#1a1a1a] rounded p-6 text-center">
                <div class="text-4xl font-bold text-[#00ff88]" x-text="memoryStats[key]"></div>
                <div class="text-xs text-[#666] uppercase tracking-wider mt-2" x-text="label"></div>
            </div>
        </template>
    </div>
</div>

<!-- Connectors Tab -->
<div x-show="activeTab === 'connectors'">
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <template x-for="c in connectors" :key="c.name">
            <div class="bg-[#141414] border border-[#1a1a1a] rounded p-4">
                <div class="flex items-center gap-2 mb-2">
                    <span class="w-2 h-2 rounded-full" :class="c.status === 'configured' ? 'bg-green-400' : 'bg-red-400'"></span>
                    <span class="font-bold text-[#00ff88]" x-text="c.name"></span>
                    <span :class="c.status === 'configured' ? 'text-green-400' : 'text-red-400'" class="text-xs" x-text="c.status"></span>
                </div>
                <div x-show="c.owner" class="text-xs text-[#666]"><span x-text="c.owner + '/' + c.repo"></span></div>
            </div>
        </template>
        <div x-show="connectors.length === 0" class="text-[#555] text-sm py-8">No connectors configured</div>
    </div>
</div>

<!-- Config Tab -->
<div x-show="activeTab === 'config'">
    <div class="bg-[#141414] border border-[#1a1a1a] rounded p-4">
        <template x-for="[key, val] in Object.entries(configData)" :key="key">
            <div class="flex justify-between py-1 border-b border-[#1a1a1a]/50 text-sm">
                <span class="text-[#999]" x-text="key"></span>
                <span class="text-[#00ff88]" x-text="typeof val === 'object' ? JSON.stringify(val) : String(val)"></span>
            </div>
        </template>
    </div>
</div>
```

**Step 2: Verify manually**

Memory tab shows 3 big number cards. Connectors shows configured integrations. Config shows key-value pairs.

**Step 3: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): memory, connectors, and config tabs"
```

---

### Task 11: Final polish and full test

**Files:**
- Modify: `src/atlas/integrations/dashboard_ui.html`

**Step 1: Add JetBrains Mono font**

Add to `<head>`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
```

Update Tailwind config inline:

```html
<script>
tailwind.config = { theme: { extend: { fontFamily: { mono: ['JetBrains Mono', 'monospace'] } } } }
</script>
```

**Step 2: Add page title and footer**

Add a small footer with version info:

```html
<div class="text-center text-[#333] text-xs py-2">ATLAS Autonomous Agent Dashboard</div>
```

**Step 3: Run full test suite**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 4: Run lint**

Run: `ruff check src/ tests/`
Expected: Clean

**Step 5: Manual end-to-end verification**

```bash
# Ensure config enables dashboard
mkdir -p ~/.atlas/config
cat > ~/.atlas/config/atlas.yaml << 'EOF'
webhook:
  enabled: true
  dashboard_enabled: true
  port: 8484
EOF

atlas daemon start
open http://localhost:8484/
```

Verify:
- Status bar shows running state, uptime counting, health dots green
- Goal input accepts text and submits
- Pause/Resume/Kill buttons work
- All 8 tabs render with data
- Missions expand to show tasks
- Trust recommendations have working accept/dismiss buttons
- Rules can be added and removed
- Audit log scrolls
- Memory shows stat cards
- Auto-refresh updates data every 5 seconds

```bash
atlas daemon stop
```

**Step 6: Commit**

```bash
git add src/atlas/integrations/dashboard_ui.html
git commit -m "feat(dashboard): font, polish, and final integration"
```

---

### Task 12: Update manual testing plan

**Files:**
- Modify: `docs/plans/manual-testing-plan.md`

**Step 1: Update Test 8 (Dashboard API)**

Replace the curl-only instructions with browser-based testing:

```markdown
## Test 8: Dashboard UI

**What it tests:** Web dashboard served by daemon, all tabs, interactive controls.

1. Enable dashboard in config and start daemon
2. Open `http://localhost:8484/` in a browser
3. Verify status bar shows running state, uptime, health indicators
4. Submit a goal via the input field
5. Click through all 8 tabs and verify data renders
6. Test emergency controls (pause/resume)
7. Add and remove an approval rule
8. Accept or dismiss a trust recommendation (if one exists)
```

**Step 2: Commit**

```bash
git add docs/plans/manual-testing-plan.md
git commit -m "docs: update manual testing plan for dashboard UI"
```

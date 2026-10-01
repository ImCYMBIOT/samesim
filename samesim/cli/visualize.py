"""
Visualization utility to compile simulation results into an interactive HTML dashboard.

Reads the CSV files and summary.json from a results directory and writes a self-contained
dashboard.html featuring interactive Plotly charts and a Vis.js network state animator.
"""
from __future__ import annotations

import csv
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SameSim Experiment Dashboard: {{ experiment_name }}</title>
    <!-- Tailwind CSS CDN -->
    <script src="https://cdn.tailwindcss.com"></script>
    <!-- Plotly.js CDN -->
    <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
    <!-- Vis.js Network CDN -->
    <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
    
    <style>
        body {
            background-color: #0b0f19;
            color: #f1f5f9;
            font-family: 'Inter', system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .glass-card {
            background: rgba(17, 24, 39, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 1rem;
        }
        /* Custom scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #0b0f19;
        }
        ::-webkit-scrollbar-thumb {
            background: #1e293b;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #334155;
        }
    </style>
</head>
<body class="p-6 lg:p-10">

    <div class="max-w-7xl mx-auto space-y-8">
        
        <!-- Header -->
        <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-800 pb-6">
            <div>
                <span class="text-xs font-semibold tracking-wider text-indigo-400 uppercase">SameSim Platform</span>
                <h1 class="text-3xl lg:text-4xl font-extrabold tracking-tight mt-1 text-transparent bg-clip-text bg-gradient-to-r from-white via-slate-200 to-slate-400">
                    {{ experiment_name }}
                </h1>
            </div>
            <div class="flex items-center gap-2 bg-indigo-500/10 border border-indigo-500/20 px-3 py-1.5 rounded-full text-indigo-300 text-sm font-medium">
                <span class="w-2 h-2 rounded-full bg-indigo-400 animate-pulse"></span>
                Seeded Run: #{{ seed }}
            </div>
        </div>

        <!-- Metadata Section -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div class="glass-card p-6 flex flex-col justify-between">
                <span class="text-slate-400 text-xs font-semibold uppercase tracking-wider">Agents</span>
                <span class="text-3xl font-bold mt-2 text-white">{{ num_agents }}</span>
                <span class="text-slate-500 text-xs mt-1">Total simulation entities</span>
            </div>
            <div class="glass-card p-6 flex flex-col justify-between">
                <span class="text-slate-400 text-xs font-semibold uppercase tracking-wider">Virtual Duration</span>
                <span class="text-3xl font-bold mt-2 text-white">{{ max_virtual_time }} ticks</span>
                <span class="text-slate-500 text-xs mt-1">Simulation duration</span>
            </div>
            <div class="glass-card p-6 flex flex-col justify-between">
                <span class="text-slate-400 text-xs font-semibold uppercase tracking-wider">Wall-clock Time</span>
                <span class="text-3xl font-bold mt-2 text-white">{{ runtime_seconds }}s</span>
                <span class="text-slate-500 text-xs mt-1">Simulation execution speed</span>
            </div>
            <div class="glass-card p-6 flex flex-col justify-between">
                <span class="text-slate-400 text-xs font-semibold uppercase tracking-wider">Topology</span>
                <span class="text-lg font-bold mt-2 text-indigo-400 truncate" title="{{ topology }}">{{ topology_short }}</span>
                <span class="text-slate-500 text-xs mt-1">Network structure plugin</span>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <!-- Sidebar Plugins details -->
            <div class="glass-card p-6 lg:col-span-1 space-y-6">
                <h3 class="text-lg font-bold text-white border-b border-slate-800 pb-3">Plugin Pipeline</h3>
                
                <div class="space-y-4">
                    <div>
                        <label class="text-slate-400 text-xs uppercase tracking-wider font-semibold block">Behavior Model</label>
                        <span class="text-sm font-mono text-indigo-300 block truncate mt-1" title="{{ behavior }}">{{ behavior }}</span>
                    </div>
                    <div>
                        <label class="text-slate-400 text-xs uppercase tracking-wider font-semibold block">Communication Port</label>
                        <span class="text-sm font-mono text-indigo-300 block truncate mt-1" title="{{ communication }}">{{ communication }}</span>
                    </div>
                    <div>
                        <label class="text-slate-400 text-xs uppercase tracking-wider font-semibold block">Network Topology</label>
                        <span class="text-sm font-mono text-indigo-300 block truncate mt-1" title="{{ topology }}">{{ topology }}</span>
                    </div>
                </div>
                
                <div class="pt-4 border-t border-slate-800 space-y-2">
                    <span class="text-xs text-slate-500 block">Reproducibility Checksum:</span>
                    <span class="text-xs font-mono bg-slate-900 px-2 py-1 rounded block text-slate-400 overflow-x-auto">
                        seed={{ seed }}&version={{ schema_version }}
                    </span>
                </div>
            </div>

            <!-- Dynamic Charts Area -->
            <div class="lg:col-span-2 space-y-6">
                <div class="glass-card p-6">
                    <h3 class="text-lg font-bold text-white border-b border-slate-800 pb-3 mb-4">Simulation Metrics</h3>
                    <div id="chart-container" class="w-full h-96"></div>
                </div>
            </div>
        </div>

        <!-- Network State Animator -->
        <div id="animator-card" class="glass-card p-6 hidden">
            <div class="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 border-b border-slate-800 pb-3 mb-4">
                <div>
                    <h3 class="text-lg font-bold text-white">Interactive Network Animation</h3>
                    <p class="text-slate-400 text-xs mt-1">Animate real-time state evolution across the network topology</p>
                </div>
                <!-- Animation controls -->
                <div class="flex items-center gap-2 flex-wrap">
                    <button id="btn-play" class="bg-indigo-600 hover:bg-indigo-500 text-white px-4 py-1.5 rounded-lg text-sm font-semibold transition">Play</button>
                    <button id="btn-pause" class="bg-slate-800 hover:bg-slate-700 text-white px-4 py-1.5 rounded-lg text-sm font-semibold transition">Pause</button>
                    <button id="btn-reset" class="bg-slate-800 hover:bg-slate-700 text-white px-4 py-1.5 rounded-lg text-sm font-semibold transition">Reset</button>
                    <div class="flex items-center gap-2 ml-4">
                        <label for="slider-tick" class="text-slate-400 text-xs">Tick:</label>
                        <input id="slider-tick" type="range" min="0" max="0" value="0" class="w-32 accent-indigo-500">
                        <span id="label-tick" class="text-sm font-mono w-8 text-right">0</span>
                    </div>
                </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-4 gap-6">
                <!-- Vis Network Container -->
                <div class="lg:col-span-3 border border-slate-800 rounded-lg overflow-hidden bg-slate-950/50 relative">
                    <div id="network-container" class="w-full h-[500px]"></div>
                    <div class="absolute bottom-4 left-4 bg-slate-900/90 border border-slate-800 px-3 py-1.5 rounded text-xs space-y-1">
                        <div class="font-semibold text-slate-300">Controls:</div>
                        <div class="text-slate-400">Drag nodes to rearrange. Scroll to zoom.</div>
                    </div>
                </div>
                
                <!-- Status List / Legend -->
                <div class="glass-card p-4 space-y-4">
                    <h4 class="font-semibold text-white border-b border-slate-800 pb-2">Legend & Stats</h4>
                    <div id="legend-container" class="space-y-3">
                        <!-- Populated by script -->
                    </div>
                </div>
            </div>
        </div>

    </div>

    <!-- Inject data variables -->
    <script>
        const experimentData = {{ data_json }};
    </script>

    <!-- UI Logic & Vis/Plotly Script -->
    <script>
        document.addEventListener("DOMContentLoaded", () => {
            const summary = experimentData.summary;
            const metrics = experimentData.metrics || {};
            const topology = experimentData.topology || [];
            const stateTrace = experimentData.state_trace || {};

            // --- 1. Populate Metrics Chart ---
            const plotData = [];
            
            // Format standard line plots
            for (const [metricName, series] of Object.entries(metrics)) {
                if (metricName === "topology" || metricName === "state_trace") continue;
                
                plotData.push({
                    x: series.x,
                    y: series.y,
                    name: metricName.replace(/_/g, ' '),
                    type: 'scatter',
                    mode: 'lines+markers',
                    line: { width: 3 },
                    marker: { size: 6 }
                });
            }

            const layout = {
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: { color: '#94a3b8' },
                xaxis: { title: 'Virtual Time (Ticks)', gridcolor: '#1e293b' },
                yaxis: { title: 'Value', gridcolor: '#1e293b' },
                margin: { t: 20, r: 20, l: 50, b: 50 },
                legend: { orientation: 'h', y: -0.2 }
            };

            if (plotData.length > 0) {
                Plotly.newPlot('chart-container', plotData, layout);
            } else {
                document.getElementById('chart-container').innerHTML = 
                    `<div class="flex items-center justify-center h-full text-slate-500">No time-series metrics found in this run.</div>`;
            }

            // --- 2. Setup Vis Network Animation if Topology is present ---
            if (topology.length > 0) {
                const animatorCard = document.getElementById('animator-card');
                animatorCard.classList.remove('hidden');

                // Determine simulation frames
                const ticks = Object.keys(stateTrace).map(Number).sort((a,b) => a - b);
                const maxTick = ticks.length > 0 ? Math.max(...ticks) : 0;
                
                const sliderTick = document.getElementById('slider-tick');
                const labelTick = document.getElementById('label-tick');
                sliderTick.max = maxTick;

                // Create vis dataset structures
                const nodesArray = [];
                const agentIds = new Set();
                
                // Extract all agent IDs from topology edges
                topology.forEach(edge => {
                    agentIds.add(edge.source);
                    agentIds.add(edge.target);
                });

                agentIds.forEach(id => {
                    nodesArray.push({
                        id: id,
                        label: `A${id}`,
                        color: { background: '#3b82f6', border: '#1d4ed8' },
                        font: { color: '#ffffff', size: 10 },
                        size: 15
                    });
                });

                const edgesArray = topology.map((edge, idx) => ({
                    id: idx,
                    from: edge.source,
                    to: edge.target,
                    color: { color: '#334155', highlight: '#6366f1' }
                }));

                const nodesDS = new vis.DataSet(nodesArray);
                const edgesDS = new vis.DataSet(edgesArray);

                const container = document.getElementById('network-container');
                const data = { nodes: nodesDS, edges: edgesDS };
                const options = {
                    physics: {
                        stabilization: true,
                        barnesHut: {
                            gravitationalConstant: -2000,
                            centralGravity: 0.3,
                            springLength: 95,
                            springConstant: 0.04
                        }
                    },
                    nodes: { shape: 'dot' },
                    interaction: { hover: true }
                };

                const network = new vis.Network(container, data, options);

                // Animation parameters
                let currentTick = 0;
                let isPlaying = false;
                let playTimer = null;

                // Color Helper based on behavior & values
                function getNodeColor(val) {
                    // 1. SIR Model Status
                    if (val === 'S') return { bg: '#3b82f6', border: '#1d4ed8', text: 'Susceptible' };
                    if (val === 'I') return { bg: '#ef4444', border: '#b91c1c', text: 'Infected' };
                    if (val === 'R') return { bg: '#06b6d4', border: '#0891b2', text: 'Recovered' };

                    // 2. Numerical Values (Gossip)
                    const parsedFloat = parseFloat(val);
                    if (!isNaN(parsedFloat)) {
                        // Map float value [0, 1] to purple gradient
                        const intensity = Math.min(255, Math.max(0, Math.floor(parsedFloat * 255)));
                        const hexVal = intensity.toString(16).padStart(2, '0');
                        return { bg: `#${hexVal}50b0`, border: '#8b5cf6', text: `Val: ${parsedFloat.toFixed(3)}` };
                    }

                    // 3. Leader election (Hash values to distinct colors)
                    if (val !== undefined && val !== null) {
                        const hash = String(val).split("").reduce((a, b) => { a = ((a << 5) - a) + b.charCodeAt(0); return a & a }, 0);
                        const hue = Math.abs(hash) % 360;
                        return { bg: `hsl(${hue}, 70%, 50%)`, border: `hsl(${hue}, 70%, 40%)`, text: `Leader: ${val}` };
                    }

                    return { bg: '#64748b', border: '#475569', text: 'Unknown' };
                }

                function updateNetworkState(tick) {
                    const tickData = stateTrace[tick] || {};
                    const counts = {};
                    
                    nodesDS.forEach(node => {
                        const val = tickData[node.id];
                        const colScheme = getNodeColor(val);
                        
                        // Count state frequencies
                        const label = colScheme.text.split(':')[0];
                        counts[label] = (counts[label] || 0) + 1;

                        nodesDS.update({
                            id: node.id,
                            color: { background: colScheme.bg, border: colScheme.border }
                        });
                    });

                    // Update legend metrics
                    const legendContainer = document.getElementById('legend-container');
                    let legendHtml = '';
                    for (const [state, cnt] of Object.entries(counts)) {
                        let colorBadge = '#64748b';
                        if (state === 'Susceptible') colorBadge = '#3b82f6';
                        else if (state === 'Infected') colorBadge = '#ef4444';
                        else if (state === 'Recovered') colorBadge = '#06b6d4';
                        else if (state.startsWith('Val')) colorBadge = '#8b5cf6';
                        else colorBadge = '#ec4899';

                        legendHtml += `
                            <div class="flex items-center justify-between bg-slate-900/50 border border-slate-800 px-3 py-2 rounded">
                                <div class="flex items-center gap-2">
                                    <span class="w-3.5 h-3.5 rounded" style="background-color: ${colorBadge}"></span>
                                    <span class="text-sm text-slate-300 font-medium">${state}</span>
                                </div>
                                <span class="font-mono text-sm font-bold text-white">${cnt}</span>
                            </div>
                        `;
                    }
                    legendContainer.innerHTML = legendHtml;
                }

                function setTick(tick) {
                    currentTick = tick;
                    sliderTick.value = tick;
                    labelTick.textContent = tick;
                    updateNetworkState(tick);
                }

                // Initialize state
                setTick(0);

                // Play / Pause Logic
                function play() {
                    if (isPlaying) return;
                    isPlaying = true;
                    document.getElementById('btn-play').textContent = 'Pause';
                    
                    playTimer = setInterval(() => {
                        if (currentTick >= maxTick) {
                            pause();
                        } else {
                            setTick(currentTick + 1);
                        }
                    }, 400); // Frame duration 400ms
                }

                function pause() {
                    isPlaying = false;
                    document.getElementById('btn-play').textContent = 'Play';
                    clearInterval(playTimer);
                }

                document.getElementById('btn-play').addEventListener('click', () => {
                    if (isPlaying) pause(); else play();
                });
                document.getElementById('btn-pause').addEventListener('click', pause);
                document.getElementById('btn-reset').addEventListener('click', () => {
                    pause();
                    setTick(0);
                });

                sliderTick.addEventListener('input', (e) => {
                    pause();
                    setTick(parseInt(e.target.value));
                });
            }
        });
    </script>
</body>
</html>
"""


def load_csv(path: Path) -> list[dict[str, str]]:
    """Parse CSV rows skipping lines starting with #."""
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        lines = [line for line in f if not line.strip().startswith("#")]
        reader = csv.DictReader(lines)
        for row in reader:
            rows.append(row)
    return rows


def generate_dashboard(results_dir: Path) -> Path:
    """Read summary.json and all CSV files, then output dashboard.html."""
    summary_path = results_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(
            f"No summary.json found in {results_dir}. "
            "Please run the simulation first."
        )

    with open(summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    metrics_data = {}
    topology_data = []
    state_trace_data = {}

    # Read each output file listed in summary
    for filepath_str in summary.get("output_files", []):
        filepath = Path(filepath_str)
        if not filepath.exists():
            # Try to resolve relative to results_dir if absolute path doesn't exist
            filepath = results_dir / filepath.name
            if not filepath.exists():
                logger.warning("Output file missing: %s", filepath_str)
                continue

        metric_name = filepath.stem.replace(f"{summary['experiment_name']}_", "")
        rows = load_csv(filepath)

        if metric_name == "topology":
            # Topology file holds source, target columns
            for row in rows:
                topology_data.append({
                    "source": row.get("source"),
                    "target": row.get("target"),
                })
        elif metric_name == "state_trace":
            # State trace file holds columns: virtual_time, value, agent_id, state
            for row in rows:
                vt = float(row.get("virtual_time", 0.0))
                agent_id = row.get("agent_id")
                state = row.get("state")
                
                # Group by tick
                tick_dict = state_trace_data.setdefault(int(vt), {})
                tick_dict[agent_id] = state
        else:
            # Time-series values: x is virtual_time, y is value
            x_vals = []
            y_vals = []
            for row in rows:
                vt_str = row.get("virtual_time")
                val_str = row.get("value")
                if vt_str is not None and val_str is not None:
                    x_vals.append(float(vt_str))
                    y_vals.append(float(val_str))
            
            metrics_data[metric_name] = {
                "x": x_vals,
                "y": y_vals,
            }

    # Prepare injected JSON object
    data_json = json.dumps({
        "summary": summary,
        "metrics": metrics_data,
        "topology": topology_data,
        "state_trace": state_trace_data
    })

    # Render template manually
    html_content = HTML_TEMPLATE
    html_content = html_content.replace("{{ experiment_name }}", summary["experiment_name"])
    html_content = html_content.replace("{{ seed }}", str(summary["seed"]))
    html_content = html_content.replace("{{ num_agents }}", str(summary["num_agents"]))
    html_content = html_content.replace("{{ max_virtual_time }}", str(summary["max_virtual_time"]))
    html_content = html_content.replace("{{ runtime_seconds }}", f"{summary['wall_clock_runtime_seconds']:.4f}")
    html_content = html_content.replace("{{ topology }}", summary["topology_plugin"])
    html_content = html_content.replace("{{ topology_short }}", summary["topology_plugin"].rsplit(".", 1)[-1])
    html_content = html_content.replace("{{ behavior }}", summary["behavior_plugin"])
    html_content = html_content.replace("{{ communication }}", summary["communication_plugin"])
    html_content = html_content.replace("{{ schema_version }}", summary["schema_version"])
    html_content = html_content.replace("{{ data_json }}", data_json)

    dashboard_path = results_dir / "dashboard.html"
    with open(dashboard_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return dashboard_path


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Generate interactive HTML dashboard for SameSim results.")
    parser.add_argument("results_dir", type=Path, help="Directory containing experiment results and summary.json")
    args = parser.parse_args()

    try:
        db_path = generate_dashboard(args.results_dir)
        print(f"Success! Dashboard written to: {db_path.resolve()}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

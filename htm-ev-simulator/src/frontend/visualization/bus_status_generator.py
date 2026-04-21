"""
Bus status generator for displaying bus states over time.
Generates a table showing all buses' SOC, state, and assignment status at different time points.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional, TYPE_CHECKING
from datetime import datetime
from collections import defaultdict

if TYPE_CHECKING:
    # ✅ Import from engines.transport_engine (adapter layer)
    from engines.transport_engine import TransportSimulationEngine
    # Backward compatibility alias
    SecondBasedSimulationEngine = TransportSimulationEngine


def generate_bus_status_section(
    sim: "SecondBasedSimulationEngine",
    bus_log: List[Dict[str, Any]],
    planning_log: List[Dict[str, Any]],
    laadinfra_log: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Generate HTML section showing bus status over time.
    
    Args:
        sim: The simulation engine
        bus_log: List of bus log events
        planning_log: List of planning log events
        laadinfra_log: List of laadinfra log events (for charging SOC updates)
        
    Returns:
        HTML string for bus status section
    """
    # Get all buses
    all_buses = sim.world.buses
    bus_count = len(all_buses)
    
    # Create a mapping of bus_vin to bus_number for easy lookup
    bus_vin_to_number = {bus.vin_number: bus.vehicle_number for bus in all_buses}
    
    # Build timeline of bus states
    # We'll sample at regular intervals (every 5 minutes)
    sim_start_time = sim.current_time if hasattr(sim, 'current_time') else 0
    # Get simulation start time from first event or config
    if bus_log:
        sim_start_time = min(log.get('time', sim_start_time) for log in bus_log)
    
    # Sample every 5 minutes
    timeline_points = []
    current_time = sim_start_time
    sample_interval = 5 * 60  # 5 minutes in seconds
    
    # Find simulation end time
    if bus_log:
        sim_end_time = max(log.get('time', current_time) for log in bus_log)
    else:
        sim_end_time = current_time + 24 * 3600  # Default to 24 hours
    
    # Build state timeline for each bus
    bus_states_timeline = defaultdict(dict)  # {bus_vin: {time: state}}
    bus_soc_timeline = defaultdict(dict)  # {bus_vin: {time: soc}}
    bus_locations_timeline = defaultdict(dict)  # {bus_vin: {time: location_name}}
    bus_assigned_blocks = defaultdict(dict)  # {bus_vin: {time: block_id}}
    bus_connector_timeline = defaultdict(dict)  # {bus_vin: {time: connector_id}} - tracks which connector is being used
    bus_charging_stopped_timeline = defaultdict(list)  # {bus_vin: [stop_times]} - tracks when charging stopped
    bus_power_timeline = defaultdict(dict)  # {bus_vin: {time: power_kw}} - tracks charging power over time
    
    # Process bus_log to build state, SOC, and location timeline
    for log in bus_log:
        event_type = log.get('event')
        bus_vin = log.get('bus_vin')
        time = log.get('time')
        
        if not bus_vin or time is None:
            continue
        
        if event_type == 'state_update':
            state = log.get('state')
            if state:
                bus_states_timeline[bus_vin][time] = state
            
            # Also get location from state_update events
            location_info = log.get('location')
            if location_info:
                location_name = location_info.get('name', 'Unknown')
                bus_locations_timeline[bus_vin][time] = location_name
        
        if event_type in ['state_update', 'soc_update']:
            soc = log.get('soc_percent')
            if soc is not None:
                bus_soc_timeline[bus_vin][time] = soc
    
    # Process laadinfra_log to get SOC updates during charging
    # This is important because charging SOC updates are logged in laadinfra_log, not bus_log
    if laadinfra_log:
        for log in laadinfra_log:
            event_type = log.get('event')
            bus_vin = log.get('bus_vin')
            time = log.get('time')
            
            if not bus_vin or time is None:
                continue
            
            # Extract SOC from charging events (including stop snapshots).
            if event_type in ['charging_progress', 'charging_started', 'charging_stopped']:
                soc = log.get('soc_percent')
                if soc is not None:
                    # Update SOC timeline - charging events provide SOC updates during charging
                    # If there's already a SOC value at this exact time, prefer charging_progress (more accurate)
                    if time not in bus_soc_timeline[bus_vin]:
                        bus_soc_timeline[bus_vin][time] = soc
                    elif event_type == 'charging_progress':
                        # charging_progress events are more accurate for charging SOC updates
                        bus_soc_timeline[bus_vin][time] = soc

                # Extract charging power from laadinfra log (connector current power in kW)
                power_kw = log.get('power_kw')
                if power_kw is not None:
                    # Similar rule as SOC: allow charging_progress to override charging_started at the same timestamp
                    if time not in bus_power_timeline[bus_vin]:
                        bus_power_timeline[bus_vin][time] = power_kw
                    elif event_type == 'charging_progress':
                        bus_power_timeline[bus_vin][time] = power_kw

                # Track connector_id when charging starts or progresses
                if event_type == 'charging_started':
                    connector_id = log.get('connector_id', 'N/A')
                    if connector_id and connector_id != 'N/A':
                        bus_connector_timeline[bus_vin][time] = connector_id
                elif event_type == 'charging_progress':
                    # For charging_progress, keep the connector_id from the most recent charging_started
                    connector_id = log.get('connector_id', 'N/A')
                    if connector_id and connector_id != 'N/A':
                        bus_connector_timeline[bus_vin][time] = connector_id
            
            # Track when charging stops
            if event_type == 'charging_stopped':
                bus_charging_stopped_timeline[bus_vin].append(time)
    
    # Process planning_log to build assignment timeline
    for log in planning_log:
        event_type = log.get('event')
        bus_vin = log.get('bus_vin')
        time = log.get('time')
        block_id = log.get('block_id')
        
        if not bus_vin or time is None:
            continue
        
        if event_type == 'block_assigned':
            bus_assigned_blocks[bus_vin][time] = block_id
        elif event_type == 'journey_start' and block_id:
            # Journey start implies this bus is actively serving this block.
            bus_assigned_blocks[bus_vin][time] = block_id
        elif event_type == 'journey_replacement' and block_id:
            # Replacement bus takes over current block at replacement time.
            replacement_bus_vin = log.get('replacement_bus_vin')
            replacement_time = log.get('time')
            if replacement_bus_vin and replacement_time is not None:
                bus_assigned_blocks[replacement_bus_vin][replacement_time] = block_id
        elif event_type == 'block_completed':
            # Block completed - clear assignment after this time
            bus_assigned_blocks[bus_vin][time] = None
        elif event_type == 'journey_end' and block_id:
            # Fallback clear to avoid stale assignment if block_completed is missing.
            bus_assigned_blocks[bus_vin][time] = None
    
    # Generate timeline points (every 5 minutes)
    while current_time <= sim_end_time:
        timeline_points.append(current_time)
        current_time += sample_interval
    
    # Build HTML table
    html_parts = []
    html_parts.append(f"""
    <div class="bus-status-section">
        <h2>Bus Status Over Time</h2>
        <p>Total Buses: {bus_count}</p>
        <p>Time interval: 5 minutes</p>
        
        <div style="margin: 1rem 0; display: flex; gap: 2rem; align-items: center; flex-wrap: wrap;">
            <div style="flex: 1; min-width: 300px;">
                <label for="time-slider">Time: </label>
                <input type="range" id="time-slider" min="0" max="{len(timeline_points) - 1}" value="0" 
                       style="width: 60%; margin: 0 1rem;">
                <span id="current-time-display">{datetime.fromtimestamp(timeline_points[0] if timeline_points else 0).strftime('%Y-%m-%d %H:%M')}</span>
            </div>
            <div style="flex: 0 0 auto;">
                <button id="play-pause-btn" onclick="togglePlayPause()" style="padding: 8px 16px; font-size: 1rem; cursor: pointer; background-color: #007bff; color: white; border: none; border-radius: 4px;">
                    ▶ Play
                </button>
            </div>
        </div>
        
        <div id="status-statistics" style="margin: 1rem 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem;">
            <div class="stat-card" style="background-color: #d4edda; padding: 1rem; border-radius: 4px; border: 1px solid #c3e6cb;">
                <div style="font-size: 0.9rem; color: #155724; margin-bottom: 0.5rem;">Total Running</div>
                <div id="stat-running" style="font-size: 1.5rem; font-weight: bold; color: #155724;">0</div>
            </div>
            <div class="stat-card" style="background-color: #fff3cd; padding: 1rem; border-radius: 4px; border: 1px solid #ffeaa7;">
                <div style="font-size: 0.9rem; color: #856404; margin-bottom: 0.5rem;">Total Charging</div>
                <div id="stat-charging" style="font-size: 1.5rem; font-weight: bold; color: #856404;">0</div>
            </div>
            <div class="stat-card" style="background-color: #d1ecf1; padding: 1rem; border-radius: 4px; border: 1px solid #bee5eb;">
                <div style="font-size: 0.9rem; color: #0c5460; margin-bottom: 0.5rem;">Total Available</div>
                <div id="stat-available" style="font-size: 1.5rem; font-weight: bold; color: #0c5460;">0</div>
            </div>
            <div class="stat-card" style="background-color: #f8d7da; padding: 1rem; border-radius: 4px; border: 1px solid #f5c6cb;">
                <div style="font-size: 0.9rem; color: #721c24; margin-bottom: 0.5rem;">No Status (-)</div>
                <div id="stat-unknown" style="font-size: 1.5rem; font-weight: bold; color: #721c24;">0</div>
            </div>
        </div>
        
        <div style="overflow-x: auto; max-height: 80vh; overflow-y: auto;">
            <table id="bus-status-table" class="bus-status-table">
                <thead>
                    <tr>
                        <th>Bus Nr</th>
                        <th>Last Charged Connector</th>
                        <th>Charging Power (kW)</th>
                        <th>State</th>
                        <th>SOC (%)</th>
                        <th>Assigned Block</th>
                        <th>Location</th>
                    </tr>
                </thead>
                <tbody id="bus-status-tbody">
""")
    
    # Generate table rows for each bus
    for bus in sorted(all_buses, key=lambda b: b.vehicle_number):
        html_parts.append(f"""
                    <tr data-bus-vin="{bus.vin_number}">
                        <td>{bus.vehicle_number}</td>
                        <td class="connector-cell" data-bus-vin="{bus.vin_number}">-</td>
                        <td class="power-cell" data-bus-vin="{bus.vin_number}">-</td>
                        <td class="state-cell" data-bus-vin="{bus.vin_number}">-</td>
                        <td class="soc-cell" data-bus-vin="{bus.vin_number}">-</td>
                        <td class="block-cell" data-bus-vin="{bus.vin_number}">-</td>
                        <td class="location-cell" data-bus-vin="{bus.vin_number}">-</td>
                    </tr>
""")
    
    html_parts.append("""
                </tbody>
            </table>
        </div>
    </div>
    
    <script>
        // Bus status data
        const busStatusData = {
            timeline: """)
    
    # Add timeline data as JSON
    import json
    timeline_json = json.dumps([datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M') for t in timeline_points])
    html_parts.append(f"{timeline_json},\n")
    
    html_parts.append("""
            busStates: """)
    
    # Build bus states data structure
    bus_states_data = {}
    for bus_vin in bus_states_timeline:
        bus_states_data[bus_vin] = {}
        for time_idx, time_point in enumerate(timeline_points):
            # Find the most recent state before or at this time
            state_at_time = None
            for state_time, state in sorted(bus_states_timeline[bus_vin].items()):
                if state_time <= time_point:
                    state_at_time = state
                else:
                    break
            if state_at_time:
                bus_states_data[bus_vin][time_idx] = state_at_time
    
    html_parts.append(f"{json.dumps(bus_states_data)},\n")
    
    html_parts.append("""
            busSOC: """)
    
    # Build bus SOC data structure
    bus_soc_data = {}
    for bus_vin in bus_soc_timeline:
        bus_soc_data[bus_vin] = {}
        for time_idx, time_point in enumerate(timeline_points):
            # Find the most recent SOC before or at this time
            soc_at_time = None
            for soc_time, soc in sorted(bus_soc_timeline[bus_vin].items()):
                if soc_time <= time_point:
                    soc_at_time = soc
                else:
                    break
            if soc_at_time is not None:
                bus_soc_data[bus_vin][time_idx] = soc_at_time
    
    html_parts.append(f"{json.dumps(bus_soc_data)},\n")
    
    html_parts.append("""
            busBlocks: """)
    
    # Build bus assignment data structure
    bus_blocks_data = {}
    for bus_vin in bus_assigned_blocks:
        bus_blocks_data[bus_vin] = {}
        for time_idx, time_point in enumerate(timeline_points):
            # Find the most recent assignment before or at this time
            block_at_time = None
            for block_time, block_id in sorted(bus_assigned_blocks[bus_vin].items()):
                if block_time <= time_point:
                    block_at_time = block_id
                else:
                    break
            if block_at_time:
                bus_blocks_data[bus_vin][time_idx] = block_at_time
    
    html_parts.append(f"{json.dumps(bus_blocks_data)},\n")
    
    html_parts.append("""
            busLocations: """)
    
    # Build bus location data structure
    bus_locations_data = {}
    for bus_vin in bus_locations_timeline:
        bus_locations_data[bus_vin] = {}
        for time_idx, time_point in enumerate(timeline_points):
            # Find the most recent location before or at this time
            location_at_time = None
            for loc_time, location_name in sorted(bus_locations_timeline[bus_vin].items()):
                if loc_time <= time_point:
                    location_at_time = location_name
                else:
                    break
            if location_at_time:
                bus_locations_data[bus_vin][time_idx] = location_at_time
    
    html_parts.append(f"{json.dumps(bus_locations_data)},\n")
    
    html_parts.append("""
            busConnectors: """)
    
    # Build bus connector data structure
    bus_connectors_data = {}
    for bus_vin in bus_connector_timeline:
        bus_connectors_data[bus_vin] = {}
        # Get sorted list of stop times for this bus
        stop_times = sorted(bus_charging_stopped_timeline.get(bus_vin, []))
        for time_idx, time_point in enumerate(timeline_points):
            # Check if there's a charging_stopped event before this time point
            # If so, and there's no charging_started after that stop, don't show connector
            has_stop_before = any(stop_time <= time_point for stop_time in stop_times)
            
            # Find the most recent connector_id before or at this time
            connector_at_time = None
            last_connector_time = None
            for connector_time, connector_id in sorted(bus_connector_timeline[bus_vin].items()):
                if connector_time <= time_point:
                    connector_at_time = connector_id
                    last_connector_time = connector_time
                else:
                    break
            
            # Only show connector if:
            # 1. We have a connector_id
            # 2. Either no stop before this time, OR the last connector_time is after the last stop before this time
            if connector_at_time:
                if has_stop_before and last_connector_time:
                    # Find the last stop before this time point
                    last_stop_before = max([st for st in stop_times if st <= time_point], default=None)
                    if last_stop_before and last_connector_time <= last_stop_before:
                        # Connector was stopped, don't show it unless there's a new charging_started after the stop
                        # Check if there's a charging_started after the last stop
                        has_restart_after_stop = any(
                            ct > last_stop_before 
                            for ct in bus_connector_timeline[bus_vin].keys()
                        )
                        if not has_restart_after_stop:
                            connector_at_time = None
                
                if connector_at_time:
                    bus_connectors_data[bus_vin][time_idx] = connector_at_time
    
    html_parts.append(f"{json.dumps(bus_connectors_data)},\n")

    html_parts.append("""
            busPowers: """)

    # Build bus charging power data structure
    bus_powers_data = {}
    for bus_vin in bus_power_timeline:
        bus_powers_data[bus_vin] = {}
        for time_idx, time_point in enumerate(timeline_points):
            # Find the most recent power value before or at this time
            power_at_time = None
            for power_time, power_kw in sorted(bus_power_timeline[bus_vin].items()):
                if power_time <= time_point:
                    power_at_time = power_kw
                else:
                    break
            if power_at_time is not None:
                bus_powers_data[bus_vin][time_idx] = power_at_time

    html_parts.append(f"{json.dumps(bus_powers_data)}\n")
    
    html_parts.append("""
        };
        
        // Update table based on time slider
        const timeSlider = document.getElementById('time-slider');
        const timeDisplay = document.getElementById('current-time-display');
        const tbody = document.getElementById('bus-status-tbody');
        let isPlaying = false;
        let playInterval = null;
        let currentTimeIndex = 0;
        
        function updateBusStatusTable(timeIndex) {
            currentTimeIndex = timeIndex;
            const timeStr = busStatusData.timeline[timeIndex];
            timeDisplay.textContent = timeStr;
            
            // Update each bus row
            const rows = tbody.querySelectorAll('tr');
            rows.forEach(row => {
                const busVin = row.getAttribute('data-bus-vin');
                const connectorCell = row.querySelector('.connector-cell');
                const powerCell = row.querySelector('.power-cell');
                const stateCell = row.querySelector('.state-cell');
                const socCell = row.querySelector('.soc-cell');
                const blockCell = row.querySelector('.block-cell');
                const locationCell = row.querySelector('.location-cell');
                
                // Update connector
                const connector = busStatusData.busConnectors && busStatusData.busConnectors[busVin] && busStatusData.busConnectors[busVin][timeIndex];
                if (connectorCell) {
                    connectorCell.textContent = connector || '-';
                }

                // Update charging power (kW)
                const power = busStatusData.busPowers 
                    && busStatusData.busPowers[busVin] 
                    && busStatusData.busPowers[busVin][timeIndex];
                if (powerCell) {
                    if (power !== undefined && power !== null) {
                        powerCell.textContent = Number(power).toFixed(1);
                    } else {
                        powerCell.textContent = '-';
                    }
                }
                
                // Update state
                const state = busStatusData.busStates[busVin] && busStatusData.busStates[busVin][timeIndex];
                if (stateCell) {
                    // If charging, show connector_id in state cell
                    if (state === 'CHARGING' && connector) {
                        stateCell.textContent = `${state} (${connector})`;
                    } else {
                        stateCell.textContent = state || '-';
                    }
                    // Color code by state
                    stateCell.className = 'state-cell';
                    if (state === 'RUNNING') {
                        stateCell.style.backgroundColor = '#d4edda';
                        stateCell.style.color = '#155724';
                    } else if (state === 'CHARGING') {
                        stateCell.style.backgroundColor = '#fff3cd';
                        stateCell.style.color = '#856404';
                    } else if (state === 'AVAILABLE') {
                        stateCell.style.backgroundColor = '#d1ecf1';
                        stateCell.style.color = '#0c5460';
                    } else if (state === 'MAINTENANCE') {
                        stateCell.style.backgroundColor = '#f8d7da';
                        stateCell.style.color = '#721c24';
                    }
                }
                
                // Update SOC
                const soc = busStatusData.busSOC[busVin] && busStatusData.busSOC[busVin][timeIndex];
                if (socCell) {
                    if (soc !== undefined && soc !== null) {
                        socCell.textContent = soc.toFixed(1) + '%';
                        // Color code by SOC level
                        socCell.className = 'soc-cell';
                        if (soc >= 80) {
                            socCell.style.backgroundColor = '#d4edda';
                        } else if (soc >= 50) {
                            socCell.style.backgroundColor = '#fff3cd';
                        } else if (soc >= 20) {
                            socCell.style.backgroundColor = '#ffeaa7';
                        } else {
                            socCell.style.backgroundColor = '#f8d7da';
                        }
                    } else {
                        socCell.textContent = '-';
                        socCell.style.backgroundColor = '';
                    }
                }
                
                // Update assigned block
                const block = busStatusData.busBlocks[busVin] && busStatusData.busBlocks[busVin][timeIndex];
                if (blockCell) {
                    blockCell.textContent = block || '-';
                }
                
                // Update location
                const location = busStatusData.busLocations[busVin] && busStatusData.busLocations[busVin][timeIndex];
                if (locationCell) {
                    locationCell.textContent = location || '-';
                }
            });
            
            // Update statistics
            let runningCount = 0;
            let chargingCount = 0;
            let availableCount = 0;
            let unknownCount = 0;
            
            rows.forEach(row => {
                const busVin = row.getAttribute('data-bus-vin');
                const state = busStatusData.busStates[busVin] && busStatusData.busStates[busVin][timeIndex];
                const soc = busStatusData.busSOC[busVin] && busStatusData.busSOC[busVin][timeIndex];
                
                if (state === 'RUNNING') {
                    runningCount++;
                } else if (state === 'CHARGING') {
                    // If bus is charging and SOC >= 80%, count as available
                    if (soc !== undefined && soc !== null && soc >= 80) {
                        availableCount++;
                    } else {
                        chargingCount++;
                    }
                } else if (state === 'AVAILABLE') {
                    availableCount++;
                } else {
                    unknownCount++;
                }
            });
            
            // Update stat cards
            document.getElementById('stat-running').textContent = runningCount;
            document.getElementById('stat-charging').textContent = chargingCount;
            document.getElementById('stat-available').textContent = availableCount;
            document.getElementById('stat-unknown').textContent = unknownCount;
        }
        
        function togglePlayPause() {
            const btn = document.getElementById('play-pause-btn');
            if (isPlaying) {
                // Pause
                if (playInterval) {
                    clearInterval(playInterval);
                    playInterval = null;
                }
                isPlaying = false;
                btn.textContent = '▶ Play';
                btn.style.backgroundColor = '#007bff';
            } else {
                // Play
                isPlaying = true;
                btn.textContent = '⏸ Pause';
                btn.style.backgroundColor = '#dc3545';
                
                playInterval = setInterval(function() {
                    if (currentTimeIndex < busStatusData.timeline.length - 1) {
                        currentTimeIndex++;
                        timeSlider.value = currentTimeIndex;
                        updateBusStatusTable(currentTimeIndex);
                    } else {
                        // Reached end, pause
                        togglePlayPause();
                    }
                }, 500); // Update every 500ms (0.5 seconds per time point)
            }
        }
        
        // Initialize with first time point
        updateBusStatusTable(0);
        
        // Update on slider change
        timeSlider.addEventListener('input', function(e) {
            const newIndex = parseInt(e.target.value);
            updateBusStatusTable(newIndex);
            // If playing, update currentTimeIndex to match slider
            if (isPlaying) {
                currentTimeIndex = newIndex;
            }
        });
    </script>
    
    <style>
        .bus-status-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.9rem;
            table-layout: fixed; /* Fixed table layout to prevent column width jumping */
        }
        .bus-status-table th {
            position: sticky;
            top: 0;
            background-color: #343a40;
            color: white;
            padding: 10px;
            text-align: left;
            z-index: 10;
        }
        .bus-status-table th:nth-child(1) { width: 8%; }   /* Bus Nr */
        .bus-status-table th:nth-child(2) { width: 18%; }  /* Last Charged Connector */
        .bus-status-table th:nth-child(3) { width: 12%; }  /* Charging Power (kW) */
        .bus-status-table th:nth-child(4) { width: 18%; }  /* State */
        .bus-status-table th:nth-child(5) { width: 10%; }  /* SOC (%) */
        .bus-status-table th:nth-child(6) { width: 15%; }  /* Assigned Block */
        .bus-status-table th:nth-child(7) { width: 29%; }  /* Location */
        .bus-status-table td {
            padding: 8px 10px;
            border: 1px solid #dee2e6;
        }
        /* Allow text wrapping for Location column, but keep others on one line */
        .bus-status-table td:not(.location-cell) {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .location-cell {
            word-wrap: break-word;
            word-break: break-word;
        }
        .bus-status-table tbody tr:hover {
            background-color: #f8f9fa;
        }
        .state-cell, .soc-cell, .power-cell {
            font-weight: 500;
            text-align: center;
        }
    </style>
""")
    
    return ''.join(html_parts)

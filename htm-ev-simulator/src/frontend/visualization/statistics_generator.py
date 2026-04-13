"""
Statistics generator for planning analysis.
Generates statistics about blocks, journeys, and bus requirements before simulation.
"""
from __future__ import annotations

from typing import Dict, List, Any, Optional, TYPE_CHECKING
from datetime import datetime, timedelta
from collections import defaultdict

if TYPE_CHECKING:
    from models import World
    from scenarios import SimulationConfig
    from models.planning import Journey


def is_return_journey(journey: "Journey") -> bool:
    """
    Check if a journey is a return journey (id starts with 8 or 9, 7 digits total).
    
    Args:
        journey: The journey to check
        
    Returns:
        True if the journey is a return journey (8xxxxxx or 9xxxxxx), False otherwise
    """
    journey_id_str = str(journey.journey_id)
    # Extract original journey_id (remove date suffix if present)
    original_journey_id = journey_id_str
    if "_" in journey_id_str:
        parts = journey_id_str.rsplit("_", 1)
        if len(parts) == 2 and len(parts[1]) == 10:  # Date part is 10 chars (YYYY-MM-DD)
            original_journey_id = parts[0]
    
    # Check if it's a return journey (8xxxxxx or 9xxxxxx - 7 digits starting with 8 or 9)
    if (len(original_journey_id) == 7 and 
        original_journey_id[0] in ['8', '9'] and 
        original_journey_id.isdigit()):
        return True
    
    return False


def analyze_planning_statistics(world: "World", config: "SimulationConfig", bus_log: Optional[List[Dict[str, Any]]] = None, skipped_blocks: Optional[set] = None, skipped_journeys: Optional[set] = None, planning_log: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Analyze planning statistics before simulation.
    
    Args:
        world: The simulation world containing blocks and journeys
        config: Simulation configuration
        bus_log: Optional bus log for running buses calculation
        skipped_blocks: Optional set of skipped blocks to exclude from statistics
        skipped_journeys: Optional set of skipped journeys to exclude from statistics
        planning_log: Optional planning log for actual block execution events
        
    Returns:
        Dictionary containing statistics:
        - total_blocks: Total number of blocks
        - total_journeys: Total number of journeys
        - total_distance_km: Total distance in kilometers
        - peak_concurrent_blocks: Maximum number of blocks running simultaneously
        - peak_time: Time when peak concurrent blocks occurred
        - concurrent_blocks_timeline: List of (time, count) tuples for chart
        - required_buses: Minimum number of buses needed
    """
    # Calculate total statistics (excluding return journeys)
    total_blocks = len(world.blocks)
    total_journeys = 0
    for block in world.blocks.values():
        for journey in block.journeys:
            if not is_return_journey(journey):
                total_journeys += 1
    
    # Calculate total distance (excluding return journeys)
    total_distance_km = 0.0
    for block in world.blocks.values():
        for journey in block.journeys:
            if not is_return_journey(journey):
                for point in journey.points:
                    if point.distance_to_next_m:
                        total_distance_km += point.distance_to_next_m / 1000.0
    
    # Calculate concurrent blocks over time
    # Use scheduled times (when blocks should be executed) for concurrent blocks calculation
    events = []  # List of (time, delta) where delta is +1 for start, -1 for end
    
    sim_start_datetime = datetime.combine(config.sim_date, config.sim_start_time)
    sim_end_datetime = sim_start_datetime + timedelta(hours=config.sim_duration_hours)
    
    # #region agent log
    import json
    debug_log_path = r"c:\Users\su1\PycharmProjects\Datalab\CHASE\.cursor\debug.log"
    try:
        with open(debug_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "statistics_generator.py:86", "message": "Starting concurrent blocks calculation (scheduled times)", "data": {"total_blocks": len(world.blocks), "has_planning_log": planning_log is not None, "planning_log_events": len(planning_log) if planning_log else 0, "sim_start": sim_start_datetime.isoformat(), "sim_end": sim_end_datetime.isoformat()}, "timestamp": datetime.now().timestamp() * 1000}) + "\n")
    except: pass
    # #endregion
    
    # Build a map of blocks that were actually assigned (from planning_log)
    actually_assigned_blocks = set()
    if planning_log:
        for log in planning_log:
            if log.get('event') == 'block_assigned':
                block_id = log.get('block_id')
                if block_id:
                    actually_assigned_blocks.add(block_id)
    
    # Use scheduled times for concurrent blocks calculation
    for block in world.blocks.values():
        if not block.journeys:
            continue
        
        # Skip blocks that were skipped during simulation
        if skipped_blocks and block in skipped_blocks:
            # #region agent log
            try:
                with open(debug_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "A", "location": "statistics_generator.py:100", "message": "Skipped block excluded from concurrent blocks", "data": {"block_id": block.block_id}, "timestamp": datetime.now().timestamp() * 1000}) + "\n")
            except: pass
            # #endregion
            continue
        
        # Filter out return journeys for block statistics
        non_return_journeys = [j for j in block.journeys if not is_return_journey(j)]
        if not non_return_journeys:
            continue  # Skip blocks that only have return journeys
        
        # Block starts when first non-return journey starts (scheduled time)
        first_journey = non_return_journeys[0]
        if first_journey.first_departure_datetime:
            block_start = first_journey.first_departure_datetime
            if block_start >= sim_start_datetime and block_start < sim_end_datetime:
                events.append((block_start.timestamp(), 1))
                # #region agent log
                was_assigned = block.block_id in actually_assigned_blocks
                try:
                    with open(debug_log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C", "location": "statistics_generator.py:115", "message": "Block scheduled start event", "data": {"block_id": block.block_id, "block_start": block_start.isoformat(), "first_journey_id": first_journey.journey_id, "was_actually_assigned": was_assigned}, "timestamp": datetime.now().timestamp() * 1000}) + "\n")
                except: pass
                # #endregion
        
        # Block ends when last non-return journey ends (scheduled time)
        last_journey = non_return_journeys[-1]
        if last_journey.points:
            last_point = last_journey.points[-1]
            if last_point.arrival_datetime:
                block_end = last_point.arrival_datetime
                if block_end >= sim_start_datetime and block_end < sim_end_datetime:
                    events.append((block_end.timestamp(), -1))
                    # #region agent log
                    try:
                        with open(debug_log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C", "location": "statistics_generator.py:125", "message": "Block scheduled end event", "data": {"block_id": block.block_id, "block_end": block_end.isoformat(), "last_journey_id": last_journey.journey_id}, "timestamp": datetime.now().timestamp() * 1000}) + "\n")
                    except: pass
                    # #endregion
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Calculate concurrent blocks at each time point
    concurrent_blocks_timeline = []
    current_count = 0
    peak_concurrent_blocks = 0
    peak_time = None
    
    # Sample every minute for the chart
    current_time = sim_start_datetime
    event_index = 0
    
    while current_time < sim_end_datetime:
        timestamp = current_time.timestamp()
        
        # Process all events up to this time
        while event_index < len(events) and events[event_index][0] <= timestamp:
            current_count += events[event_index][1]
            event_index += 1
        
        concurrent_blocks_timeline.append({
            'time': timestamp,
            'count': current_count
        })
        
        # Track peak
        if current_count > peak_concurrent_blocks:
            peak_concurrent_blocks = current_count
            peak_time = timestamp
        
        # Move to next minute
        current_time += timedelta(minutes=1)
    
    # Calculate required buses using greedy algorithm
    # This is a simplified calculation - in reality, we'd need to consider
    # bus availability, charging time, etc.
    required_buses = calculate_required_buses(world, config)
    
    # Calculate running buses over time based on block assignments and replacements
    # NEW LOGIC:
    # 1. If bus is assigned to block, running bus +1
    # 2. If there is replacement bus, running bus +1
    # 3. If replaced bus goes to garage for charging (and is not in any block), running bus -1
    # 4. When block ends (last journey_end without block_end_return_journey), running bus -1
    running_buses_timeline = []
    peak_running_buses = 0
    peak_running_time = None
    
    if planning_log and bus_log:
        # Build timeline of block assignments and replacements
        # Track: {block_id: {bus_vin, assign_time, end_time, replacement_bus_vin, replacement_time, original_bus_unassign_time}}
        block_assignments = {}  # {block_id: {'bus_vin': ..., 'assign_time': ..., 'end_time': ..., 'replacement_bus_vin': ..., 'replacement_time': ..., 'original_bus_unassign_time': ...}}
        
        # Track buses that were replaced and sent to garage
        replaced_buses_to_garage = {}  # {bus_vin: [(unassign_time, block_id), ...]}
        
        # Process planning_log to build block assignment timeline
        for log_entry in planning_log:
            event_type = log_entry.get('event')
            time = log_entry.get('time', 0)
            block_id = log_entry.get('block_id')
            
            if event_type == 'block_assigned' and block_id:
                bus_vin = log_entry.get('bus_vin')
                if bus_vin:
                    if block_id not in block_assignments:
                        block_assignments[block_id] = {}
                    block_assignments[block_id]['bus_vin'] = bus_vin
                    block_assignments[block_id]['assign_time'] = time
                    # Get block end time from world
                    block = world.blocks.get(block_id)
                    if block:
                        non_return_journeys = [j for j in block.journeys if not is_return_journey(j)]
                        if non_return_journeys:
                            last_journey = non_return_journeys[-1]
                            block_end = last_journey.points[-1].arrival_datetime if last_journey.points else None
                            if block_end:
                                block_assignments[block_id]['end_time'] = block_end.timestamp()
            
            elif event_type == 'journey_replacement' and block_id:
                replacement_bus_vin = log_entry.get('replacement_bus_vin')
                original_bus_vin = log_entry.get('bus_vin')
                if replacement_bus_vin and original_bus_vin and block_id in block_assignments:
                    block_assignments[block_id]['replacement_bus_vin'] = replacement_bus_vin
                    block_assignments[block_id]['replacement_time'] = time
                    block_assignments[block_id]['original_bus_unassign_time'] = time
                    # Track that original bus was replaced and sent to garage
                    if original_bus_vin not in replaced_buses_to_garage:
                        replaced_buses_to_garage[original_bus_vin] = []
                    replaced_buses_to_garage[original_bus_vin].append((time, block_id))
            
            elif event_type == 'journey_end' and block_id:
                # Check if this is the last journey in the block (block end)
                block = world.blocks.get(block_id)
                if block and block_id in block_assignments:
                    journey_id = log_entry.get('journey_id')
                    if journey_id:
                        # Check if this is the last non-return journey
                        non_return_journeys = [j for j in block.journeys if not is_return_journey(j)]
                        if non_return_journeys:
                            last_journey = non_return_journeys[-1]
                            if str(last_journey.journey_id) == str(journey_id):
                                # This is the last journey, block ends
                                # But check if there's a block_end_return_journey
                                has_block_end_return = any(
                                    j.journey_type == "BLOCK_END_RETURN_TO_TELEXSTRAAT" 
                                    for j in block.journeys
                                )
                                if not has_block_end_return:
                                    # Block truly ends here
                                    block_assignments[block_id]['actual_end_time'] = time
        
        # Build bus state timeline from bus_log
        bus_state_timeline = {}  # {bus_vin: [(time, state), ...]}
        for log_entry in bus_log:
            event_type = log_entry.get('event')
            if event_type == 'state_update':
                bus_vin = log_entry.get('bus_vin')
                time = log_entry.get('time')
                state = log_entry.get('state')
                
                if bus_vin and time and state:
                    if bus_vin not in bus_state_timeline:
                        bus_state_timeline[bus_vin] = []
                    bus_state_timeline[bus_vin].append((time, state))
        
        # Sort state changes for each bus by time
        for bus_vin in bus_state_timeline:
            bus_state_timeline[bus_vin].sort(key=lambda x: x[0])
        
        # Calculate running buses at each time point (same timeline as concurrent blocks)
        for point in concurrent_blocks_timeline:
            timestamp = point['time']
            concurrent_count = point['count']
            
            running_count = 0
            
            # Count buses assigned to active blocks
            active_buses = set()
            for block_id, assignment in block_assignments.items():
                assign_time = assignment.get('assign_time', 0)
                end_time = assignment.get('end_time', float('inf'))
                actual_end_time = assignment.get('actual_end_time', None)
                
                # Use actual_end_time if available, otherwise use scheduled end_time
                block_end = actual_end_time if actual_end_time is not None else end_time
                
                # Check if block is active at this timestamp
                if assign_time <= timestamp <= block_end:
                    bus_vin = assignment.get('bus_vin')
                    replacement_bus_vin = assignment.get('replacement_bus_vin')
                    replacement_time = assignment.get('replacement_time', float('inf'))
                    original_bus_unassign_time = assignment.get('original_bus_unassign_time', float('inf'))
                    
                    # Determine which bus is active at this timestamp
                    if replacement_bus_vin and replacement_time <= timestamp:
                        # Replacement bus is active
                        active_buses.add(replacement_bus_vin)
                        
                        # Original bus: check if it has reached garage and started charging
                        original_bus_vin = assignment.get('bus_vin')
                        if original_bus_vin and original_bus_unassign_time <= timestamp:
                            # Check if original bus has reached garage and started charging
                            original_bus_state = None
                            if original_bus_vin in bus_state_timeline:
                                for change_time, state in bus_state_timeline[original_bus_vin]:
                                    if change_time <= timestamp:
                                        original_bus_state = state
                                    else:
                                        break
                            
                            # If original bus is CHARGING and not in any other block, it's no longer running
                            if original_bus_state == 'CHARGING':
                                # Check if original bus is in any other active block
                                in_other_block = False
                                for other_block_id, other_assignment in block_assignments.items():
                                    if other_block_id != block_id:
                                        other_assign_time = other_assignment.get('assign_time', 0)
                                        other_end_time = other_assignment.get('end_time', float('inf'))
                                        other_actual_end_time = other_assignment.get('actual_end_time', None)
                                        other_block_end = other_actual_end_time if other_actual_end_time is not None else other_end_time
                                        
                                        if (other_assignment.get('bus_vin') == original_bus_vin or 
                                            other_assignment.get('replacement_bus_vin') == original_bus_vin):
                                            if other_assign_time <= timestamp <= other_block_end:
                                                in_other_block = True
                                                break
                                
                                if not in_other_block:
                                    # Original bus is charging and not in any block, don't count it
                                    pass  # Already not counted
                            else:
                                # Original bus is still in transit to garage, still counts as running
                                active_buses.add(original_bus_vin)
                    else:
                        # Original bus is still active
                        if bus_vin:
                            active_buses.add(bus_vin)
            
            running_count = len(active_buses)
            
            # #region agent log
            # Check for the specific time range: 2026-02-02 08:16 to 22:25
            time_range_start = datetime(2026, 2, 2, 8, 16, 0).timestamp()
            time_range_end = datetime(2026, 2, 2, 22, 25, 0).timestamp()
            if concurrent_count > running_count and timestamp >= time_range_start and timestamp <= time_range_end:
                try:
                    debug_log_path = ".cursor/debug.log"
                    with open(debug_log_path, "a", encoding="utf-8") as f:
                        time_str = datetime.fromtimestamp(timestamp).isoformat()
                        f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "statistics_generator.py:357", "message": "Concurrent blocks > Running buses", "data": {"time": time_str, "concurrent_blocks": concurrent_count, "running_buses": running_count, "diff": concurrent_count - running_count, "active_buses_count": len(active_buses)}, "timestamp": datetime.now().timestamp() * 1000}) + "\n")
                except Exception as e:
                    try:
                        debug_log_path = ".cursor/debug.log"
                        with open(debug_log_path, "a", encoding="utf-8") as f:
                            f.write(json.dumps({"sessionId": "debug-session", "runId": "run1", "hypothesisId": "B,C,D", "location": "statistics_generator.py:357", "message": "Error in logging", "data": {"error": str(e)}, "timestamp": datetime.now().timestamp() * 1000}) + "\n")
                    except: pass
            # #endregion
            
            running_buses_timeline.append({
                'time': timestamp,
                'count': running_count
            })
            
            # Track peak
            if running_count > peak_running_buses:
                peak_running_buses = running_count
                peak_running_time = timestamp
    else:
        # If no planning_log or bus_log, create empty timeline with same structure
        for point in concurrent_blocks_timeline:
            running_buses_timeline.append({
                'time': point['time'],
                'count': 0
            })
    
    return {
        'total_blocks': total_blocks,
        'total_journeys': total_journeys,
        'total_distance_km': total_distance_km,
        'peak_concurrent_blocks': peak_concurrent_blocks,
        'peak_time': peak_time,
        'concurrent_blocks_timeline': concurrent_blocks_timeline,
        'peak_running_buses': peak_running_buses,
        'peak_running_time': peak_running_time,
        'running_buses_timeline': running_buses_timeline,
        'required_buses': required_buses,
        'sim_start_time': sim_start_datetime.timestamp(),
        'sim_end_time': sim_end_datetime.timestamp()
    }


def calculate_required_buses(world: "World", config: "SimulationConfig") -> int:
    """
    Calculate minimum number of buses required to satisfy all blocks.
    NOTE: This includes ALL journeys (including return journeys) for bus requirement calculation.
    
    Uses a greedy interval scheduling approach:
    - Sort blocks by end time
    - Assign buses greedily (reuse bus if previous block ends before new block starts)
    
    Args:
        world: The simulation world
        config: Simulation configuration
        
    Returns:
        Minimum number of buses required
    """
    sim_start_datetime = datetime.combine(config.sim_date, config.sim_start_time)
    sim_end_datetime = sim_start_datetime + timedelta(hours=config.sim_duration_hours)
    
    # Create list of (start_time, end_time) for each block (including return journeys)
    block_intervals = []
    for block in world.blocks.values():
        if not block.journeys:
            continue
        
        # Include ALL journeys (including return journeys) for bus requirement calculation
        # Block starts when first journey starts
        first_journey = block.journeys[0]
        if not first_journey.first_departure_datetime:
            continue
        
        block_start = first_journey.first_departure_datetime
        if block_start < sim_start_datetime or block_start >= sim_end_datetime:
            continue
        
        # Block ends when last journey ends
        last_journey = block.journeys[-1]
        if not last_journey.points:
            continue
        
        last_point = last_journey.points[-1]
        if not last_point.arrival_datetime:
            continue
        
        block_end = last_point.arrival_datetime
        if block_end < sim_start_datetime or block_end >= sim_end_datetime:
            continue
        
        block_intervals.append((block_start.timestamp(), block_end.timestamp()))
    
    if not block_intervals:
        return 0
    
    # Sort by end time
    block_intervals.sort(key=lambda x: x[1])
    
    # Greedy assignment: track when each bus becomes available
    bus_available_times = []
    
    for start_time, end_time in block_intervals:
        # Find a bus that's available (previous block ended before this one starts)
        assigned = False
        for i, available_time in enumerate(bus_available_times):
            if available_time <= start_time:
                # Reuse this bus
                bus_available_times[i] = end_time
                assigned = True
                break
        
        if not assigned:
            # Need a new bus
            bus_available_times.append(end_time)
    
    return len(bus_available_times)


def generate_statistics_section(statistics: Dict[str, Any]) -> str:
    """
    Generate HTML section for planning statistics with chart.
    
    Args:
        statistics: Statistics dictionary from analyze_planning_statistics
        
    Returns:
        HTML string for statistics section
    """
    # Format timeline data for Chart.js
    timeline_labels = []
    concurrent_blocks_data = []
    running_buses_data = []
    
    for point in statistics['concurrent_blocks_timeline']:
        # Format as full datetime (YYYY-MM-DD HH:MM) for x-axis
        time_str = datetime.fromtimestamp(point['time']).strftime('%Y-%m-%d %H:%M')
        timeline_labels.append(time_str)
        concurrent_blocks_data.append(point['count'])
    
    # Format running buses timeline data
    for point in statistics.get('running_buses_timeline', []):
        running_buses_data.append(point['count'])
    
    # Format peak time
    peak_time_str = "N/A"
    if statistics.get('peak_time'):
        peak_time_str = datetime.fromtimestamp(statistics['peak_time']).strftime('%Y-%m-%d %H:%M:%S')
    
    import json
    
    # Format peak running buses time
    peak_running_time_str = "N/A"
    if statistics.get('peak_running_time'):
        peak_running_time_str = datetime.fromtimestamp(statistics['peak_running_time']).strftime('%Y-%m-%d %H:%M:%S')
    
    # Convert timeline data to JSON strings for JavaScript
    timeline_labels_json = json.dumps(timeline_labels)
    concurrent_blocks_data_json = json.dumps(concurrent_blocks_data)
    running_buses_data_json = json.dumps(running_buses_data)
    
    html = f"""
    <div class="statistics-section">
        <h2>Planning Statistics</h2>
        
        <div class="stats-grid">
            <div class="stat-card">
                <h3>Total Blocks</h3>
                <p class="stat-value">{statistics['total_blocks']}</p>
            </div>
            <div class="stat-card">
                <h3>Total Journeys</h3>
                <p class="stat-value">{statistics['total_journeys']}</p>
            </div>
            <div class="stat-card">
                <h3>Total Distance</h3>
                <p class="stat-value">{statistics['total_distance_km']:.2f} km</p>
            </div>
            <div class="stat-card">
                <h3>Peak Concurrent Blocks</h3>
                <p class="stat-value">{statistics['peak_concurrent_blocks']}</p>
                <p class="stat-detail">at {peak_time_str}</p>
            </div>
            <div class="stat-card">
                <h3>Peak Running Buses</h3>
                <p class="stat-value">{statistics.get('peak_running_buses', 0)}</p>
                <p class="stat-detail">at {peak_running_time_str}</p>
            </div>
            <div class="stat-card">
                <h3>Required Buses</h3>
                <p class="stat-value">{statistics['required_buses']}</p>
                <p class="stat-detail">minimum to satisfy all blocks</p>
            </div>
        </div>
        
        <div class="chart-container">
            <h3>Concurrent Blocks and Running Buses Over Time</h3>
            <canvas id="concurrentBlocksChart"></canvas>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
    <script>
        const ctx = document.getElementById('concurrentBlocksChart');
        const chartData = {{
            labels: {timeline_labels_json},
            datasets: [{{
                label: 'Concurrent Blocks',
                data: {concurrent_blocks_data_json},
                borderColor: 'rgb(75, 192, 192)',
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                tension: 0.1,
                fill: true,
                yAxisID: 'y'
            }}, {{
                label: 'Running Buses',
                data: {running_buses_data_json},
                borderColor: 'rgb(255, 99, 132)',
                backgroundColor: 'rgba(255, 99, 132, 0.2)',
                tension: 0.1,
                fill: true,
                yAxisID: 'y'
            }}]
        }};
        
        new Chart(ctx, {{
            type: 'line',
            data: chartData,
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                plugins: {{
                    title: {{
                        display: true,
                        text: 'Concurrent Blocks and Running Buses Over Time'
                    }},
                    legend: {{
                        display: true
                    }}
                }},
                scales: {{
                    x: {{
                        title: {{
                            display: true,
                            text: 'Time'
                        }},
                        ticks: {{
                            maxRotation: 45,
                            minRotation: 45
                        }}
                    }},
                    y: {{
                        title: {{
                            display: true,
                            text: 'Count'
                        }},
                        beginAtZero: true,
                        ticks: {{
                            stepSize: 1
                        }}
                    }}
                }}
            }}
        }});
    </script>
    """
    
    return html

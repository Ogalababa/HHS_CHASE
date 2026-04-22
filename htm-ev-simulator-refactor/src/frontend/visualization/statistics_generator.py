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
    
    # Use scheduled times for concurrent blocks calculation.
    # Count a block as concurrent whenever its active interval overlaps with
    # the simulation horizon, then clip start/end to the horizon boundaries.
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
        
        # Build block interval from all journeys that have schedule info.
        journey_starts = [j.first_departure_datetime for j in block.journeys if j.first_departure_datetime]
        journey_ends = [
            j.points[-1].arrival_datetime
            for j in block.journeys
            if j.points and j.points[-1].arrival_datetime
        ]
        if not journey_starts or not journey_ends:
            continue

        block_start = min(journey_starts)
        block_end = max(journey_ends)
        if block_end <= block_start:
            continue

        # Clip interval to simulation horizon.
        effective_start = max(block_start, sim_start_datetime)
        effective_end = min(block_end, sim_end_datetime)

        # No overlap with horizon: skip.
        if effective_end <= effective_start:
            continue

        events.append((effective_start.timestamp(), 1))
        events.append((effective_end.timestamp(), -1))
    
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
    
    # Required buses are defined as the peak number of buses that are "running":
    # includes buses executing tasks and buses still in transit (on road) even if
    # not actively executing a journey step at that minute.
    #
    # Fallback to planning-only estimation if runtime logs are unavailable.
    required_buses = 0
    
    # Calculate running buses over time from bus runtime state timeline.
    # Rationale: assignment-based estimation can overcount during replacements and
    # delayed state transitions. Runtime state updates are the source of truth for
    # "currently running" buses in visualization.
    running_buses_timeline = []
    peak_running_buses = 0
    peak_running_time = None
    
    if planning_log and bus_log:
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

        # Collect replacement events so we can account for temporary overlap:
        # replacement bus starts block continuation while original bus can still
        # be on-road until it reaches charging/available state.
        replacement_events = []
        for log_entry in planning_log:
            if log_entry.get('event') == 'journey_replacement':
                replacement_events.append({
                    'time': log_entry.get('time', 0),
                    'original_bus_vin': log_entry.get('bus_vin'),
                })
        replacement_events.sort(key=lambda x: x['time'])

        def _state_at(vin: str, timestamp: float) -> Optional[str]:
            changes = bus_state_timeline.get(vin, [])
            state = None
            for change_time, value in changes:
                if change_time <= timestamp:
                    state = value
                else:
                    break
            return state
        
        # Calculate running buses at each time point (same timeline as concurrent blocks)
        for point in concurrent_blocks_timeline:
            timestamp = point['time']
            concurrent_count = point['count']

            # Runtime measured running buses from state timeline.
            runtime_running = 0
            for _bus_vin, changes in bus_state_timeline.items():
                current_state = None
                for change_time, state in changes:
                    if change_time <= timestamp:
                        current_state = state
                    else:
                        break
                if current_state == 'RUNNING':
                    runtime_running += 1

            # Baseline by business definition: each active block requires one bus.
            baseline_running = concurrent_count

            # Add temporary overlap buses from replacements while original still RUNNING.
            replacement_overlap = 0
            for repl in replacement_events:
                repl_time = repl.get('time', 0)
                original_vin = repl.get('original_bus_vin')
                if repl_time and original_vin and repl_time <= timestamp:
                    if _state_at(original_vin, timestamp) == 'RUNNING':
                        replacement_overlap += 1

            running_count = max(runtime_running, baseline_running + replacement_overlap)
            
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

    if planning_log and bus_log:
        required_buses = peak_running_buses
    else:
        required_buses = calculate_required_buses(world, config)
    
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

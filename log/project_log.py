"""Project log for the Corrosion Monitor integration work.

This module is intentionally plain Python so it can be imported, printed,
or copied into reports without additional formatting tools.
"""

PROJECT_LOG = """
Corrosion Monitor Project Log
Generated: 2026-04-26
Repo: corrosion
Scope: Full history of the live Pi/Teensy integration work completed so far

1. Project objective
The immediate goal was to remove the critical blocker in the real-data path:
- Pi reads real Teensy FRAME data
- Pi exposes the data reliably to the app through session APIs and SSE
- The system stops relying on synthetic sensor values for the live lab session

2. What we built
2.1 Serial ingestion layer
Created edge/serial_reader.py as a dedicated serial manager for the Teensy link.
What it does:
- Opens the Teensy serial port at /dev/ttyACM0 by default
- Reads lines in a background thread
- Parses canonical FRAME records of the form:
  FRAME:Rp:<float>;I:<float>;status:<str>;asym:<float>
- Maintains a rolling buffer of parsed frames
- Exposes callback hooks so readings can be pushed into session state
- Handles malformed lines without crashing the reader loop
- Supports reconnect/backoff behavior for transient disconnects

2.2 Session state layer
Created edge/session_state.py as a thread-safe in-memory store.
What it does:
- Tracks the active session ID
- Resets session data on demand
- Stores photos captured during a lab session
- Stores parsed sensor readings in a bounded deque
- Returns the latest reading and full snapshot lists
- Provides a singleton session_state object used by the backend

2.3 Backend integration
Updated edge/web_server.py to wire the serial reader and session store into the legacy HTTP server.
Endpoints added:
- POST /api/session/new
- POST /api/session/serial/connect
- POST /api/session/serial/disconnect
- GET /api/session/readings
- GET /api/session/readings/stream

Backend behavior added:
- Opens and manages the Teensy serial connection
- Pushes parsed FRAME data into session_state
- Streams live readings over SSE on the canonical route
- Returns structured JSON for session operations
- Uses a threaded server so SSE does not block other requests
- Enables address reuse so port 8080 can restart cleanly

2.4 Dashboard resilience fix
We found a crash path where dashboard-latest.json could contain malformed or concatenated JSON.
Fix applied:
- Added a safe loader fallback in edge/web_server.py
- If JSON parsing fails, the server falls back to the default dashboard state instead of crashing request threads

2.5 Testing
Added and verified tests for:
- Frame parsing
- Session state behavior
- Session API behavior
- SSE contract and response format

2.6 Documentation
Updated README.md with:
- Teensy connection instructions
- Session API quickstart
- SSE curl example
- Linux troubleshooting notes for /dev/ttyACM0 and dialout permissions
- pyserial installation note

3. Issues encountered and how they were resolved
3.1 Port 8080 already in use
Symptom:
- OSError: [Errno 98] Address already in use when restarting the backend
Resolution:
- Switched to a reusable threaded server class
- Set allow_reuse_address = True
- Used fuser to clean up stale listeners during testing

3.2 pytest command missing on the Pi shell
Symptom:
- Running pytest directly failed with command not found
Resolution:
- Used python3 -m pytest inside the virtual environment instead
- This ensured the correct interpreter and dependencies were used

3.3 pyserial missing on the Pi
Symptom:
- Serial connect returned serial_connect_failed
- Direct python import of serial failed with ModuleNotFoundError
Resolution:
- Installed pyserial into the Pi virtual environment
- Verified direct open of /dev/ttyACM0 succeeded

3.4 Malformed dashboard JSON
Symptom:
- /api/state crashed with json.decoder.JSONDecodeError: Extra data
- The server thread repeatedly emitted exceptions
Resolution:
- Reworked state loading to tolerate malformed or concatenated JSON
- Added a default fallback payload so the UI continues running

3.5 Teensy startup chatter causing parse warnings
Symptom:
- The serial reader logged many serial_parse_error messages
- These were banner and measurement status lines, not FRAME records
Resolution:
- Confirmed the parser was behaving correctly because it only accepts canonical FRAME lines
- Verified that valid FRAME records were still being parsed and streamed
- Accepted the warning noise as non-fatal during startup/measurement chatter

4. Pi-side validation results
The following was confirmed on the Raspberry Pi:
- /dev/ttyACM0 is present and owned by the dialout group
- pyserial can open the Teensy serial port at 115200 baud
- The backend starts successfully and serves the UI on port 8080
- /api/state returns 200 OK after the dashboard JSON fallback fix
- /api/session/new returns a valid session ID
- /api/session/serial/connect succeeds
- /api/session/readings/stream emits live SSE events
- /api/session/readings returns populated live readings

5. Teensy serial format verified
We manually probed the Teensy and confirmed the canonical frame format is being emitted:
- FRAME:Rp:307692.28;I:0.033;status:EXCELLENT;asym:0.7
- Additional frames continue to stream during measurements

This confirmed that the Pi parser and the Teensy firmware speak the same data format.

6. Test results
Local repo verification succeeded:
- tests/test_serial_reader.py
- tests/test_session_state.py
- tests/test_web_session_api.py
- 13 tests passed in the targeted run

7. Current status
Working now:
- Teensy emits valid FRAME records
- Pi opens the serial port and receives live data
- Backend ingests real readings
- SSE forwards readings to the app
- Session APIs work as expected
- Dashboard loads reliably
- Tests pass

Still pending:
- Lab Session GUI with photo capture, stepper workflow, and analysis trigger
- Real electrode-in-solution run when electrodes are available again
- Pi HQ camera validation on actual hardware
- Optional cleanup to reduce serial_parse_error log noise from non-FRAME chatter

8. Next recommended software task
Build the Lab Session GUI:
- Step 1: photo capture and gallery
- Step 2: live electrochemical readings
- Step 3: analysis trigger and result display

This is the best next software task because it prepares the guided demo workflow while the hardware side is temporarily unavailable.

9. Final summary
The core real-data path is now implemented and validated:
- Teensy FRAME data is real and live
- Pi serial ingestion exists and works
- Session APIs and SSE are live
- The backend is stable
- The system is ready for the next UX layer
""".strip() + "\n"


def get_project_log() -> str:
    """Return the full project log as plain text."""
    return PROJECT_LOG


if __name__ == "__main__":
    print(PROJECT_LOG)

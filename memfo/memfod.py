#!/usr/bin/env python3
BASH_SCRIPT_CONTENT = """#!/usr/bin/env bash
# memfod.sh
# A dedicated tmux wrapper script to manage a persistent, long-running
# session for the memfo memory monitoring tool.

# --- Configuration ---
DAEMON="memfo"           # The Python executable name (must be in PATH)
SESSION_NAME="memfo"     # Name of the tmux session
WINDOW_NAME="monitor"    # Name of the tmux window
PANE_TARGET="${SESSION_NAME}:${WINDOW_NAME}.0" # Specific pane (window 0, pane 0)

# --- Utility Functions ---

is_pane_running_daemon() {
    # Check if the DAEMON process is actively running inside the target pane's TTY.
    # This bypasses the ambiguity of tmux's '#{pane_current_command}'.
    if ! tmux has-session -t ${SESSION_NAME} 2>/dev/null; then
        return 1
    fi
    
    # 1. Get the TTY (pseudo-terminal) associated with the target pane
    PANE_TTY=$(tmux display-message -p -t ${PANE_TARGET} '#{pane_tty}' 2>/dev/null)
    
    if [ -z "$PANE_TTY" ]; then
        return 1
    fi

    # 2. Check the process table for the DAEMON running on that TTY.
    # -t "$PANE_TTY": lists processes associated with the terminal device.
    # We grep for the DAEMON name and exclude the grep process itself.
    ps -t "$PANE_TTY" -o args= | grep "${DAEMON}" | grep -v "grep ${DAEMON}" | grep -q "${DAEMON}"

    return $?
}

d_start() {
    # 1. Check if the main tmux session exists
    if ! tmux has-session -t ${SESSION_NAME} 2>/dev/null; then
        echo "NOTE: Session '${SESSION_NAME}' not found. Creating and starting '${DAEMON}'."
        
        # Create a detached session, name the window, and start the DAEMON.
        # The 'bash' command keeps the pane open if memfo exits/crashes.
        tmux new-session -d -s ${SESSION_NAME} -n ${WINDOW_NAME} "${DAEMON}; bash"
    else
        # 2. Session exists, check if the DAEMON is running inside the pane
        if ! is_pane_running_daemon; then
            echo "NOTE: Session '${SESSION_NAME}' found, but '${DAEMON}' is NOT running in pane. Respawning..."

            # We need to find or create the target window/pane before respawning
            # A simpler approach is to always target pane 0, assuming the user doesn't mess with the layout.

            if ! tmux select-window -t ${SESSION_NAME}:${WINDOW_NAME} 2>/dev/null; then
                 # If window was killed but session is alive, create the window
                 tmux new-window -d -t ${SESSION_NAME}: -n ${WINDOW_NAME} "${DAEMON}; bash"
            else
                # Window exists, respawn the existing pane (0) in the target window, keeping it open with -k
                # Note: This kills the current process (likely the dormant bash shell) and starts memfo
                tmux respawn-pane -t ${PANE_TARGET} -k "${DAEMON}; bash"
            fi
        else
            echo "NOTE: '${DAEMON}' is already running persistently in session '${SESSION_NAME}'."
        fi
    fi
}

d_attach() {
    d_start

    # 3. Attach the user to the session
    echo "Attaching to tmux session '${SESSION_NAME}'..."
    # Attempt to switch to the monitor window first
    tmux select-window -t ${SESSION_NAME}:${WINDOW_NAME} 2>/dev/null 
    tmux attach-session -t ${SESSION_NAME}
}

d_stop() {
    echo -n "Stopping ${DAEMON} and killing session '${SESSION_NAME}'..."
    
    # Send CTRL-C (SIGINT) to the pane process to attempt a graceful exit
    tmux send-keys -t ${PANE_TARGET} C-c 2>/dev/null
    sleep 1 
    
    # Hard kill the entire session for certainty, since the data is saved in memfo itself.
    if tmux has-session -t ${SESSION_NAME} 2>/dev/null; then
        tmux kill-session -t ${SESSION_NAME}
    fi
    echo " Done."
}


# --- Main Execution ---

case "$1" in
    stop)
        d_stop
        ;;
    restart|force-reload)
        echo "Restarting ${DAEMON}..."
        d_stop
        sleep 2
        d_start_or_attach
        ;;
    stat|status)
        if is_pane_running_daemon; then
            echo "NOTE: ${DAEMON} is running persistently in tmux session '${SESSION_NAME}'."
        else
            echo "NOTE: ${DAEMON} is NOT running persistently or session is dead."
        fi
        ;;
    start) # Default action: start
        d_start
        ;;
    attach|"") # Default action: attach (which starts if needed)
        d_attach
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|attach}" >&2
        exit 1
        ;;
esac

exit 0
"""


def main():
    """
    Replaces the current Python process with a bash shell that executes 
    the embedded script.
    """
    import os, sys

    # Executable path: The bash interpreter
    program = "/bin/bash"
    script_arg0 = 'memfod'
    
    # Replace the current process with the new command
    try:
        # os.execv(path, args)
        # Note: We are NOT passing sys.argv[1:] to the script's arguments 
        # via the exec call itself. We are embedding them directly into 
        # the script string (BASH_SCRIPT_CONTENT) passed to '-c'.
        
        # A simpler way is to pass the script content and then the arguments 
        # for bash's $0, $1, $2, etc. This is much cleaner:
        
        # New arguments list for execv:
        # Arg 0 ($0 in the script): The command name
        # Arg 1: The script content (to be executed by -c)
        # Arg 2 ($0 in the script): The name of the command that the user ran (e.g., 'my-bash-command')
        # Arg 3 ($1 in the script): User's first argument
        # Arg 4 ($2 in the script): User's second argument, etc.
        
        exec_args = [
            program, # Path to the executable
            "-c",    # Flag to execute the next string as a command
            BASH_SCRIPT_CONTENT, # Command to execute (the script)
            # The rest of the list are arguments passed to the executed script (which become $0, $1, $2...)
            script_arg0, # This becomes $0 inside the script (the script's name)
            *sys.argv[1:]      # The user's actual arguments, which become $1, $2, $3...
        ]
        
        os.execv(program, exec_args)
        
    except OSError as e:
        # This only runs if the execv call fails (e.g., /bin/bash not found)
        print(f"Error executing bash: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
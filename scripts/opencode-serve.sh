#!/usr/bin/env bash
set -euo pipefail

DIR="${XDG_DATA_HOME:-$HOME/.local/share}/opencode/serve-logs"
PIDFILE="$DIR/serve.pid"
LOGOUT="$DIR/serve.log"
LOGERR="$DIR/serve.err"
PORT=64763

stop_server() {
    if [[ -f "$PIDFILE" ]]; then
        local pid
        pid=$(cat "$PIDFILE")
        kill "$pid" 2>/dev/null || true
        rm -f "$PIDFILE"
        echo "Stopped (PID: $pid)"
    else
        echo "Not running"
    fi
}

show_help() {
    cat <<EOF
Usage: ./opencode-serve.sh [start|stop|restart|help]

  start    Start the server (default)
  stop     Stop the running server
  restart  Restart the server
  help     Show this help

Defaults: hostname=0.0.0.0, port=64763
Logs:     ~/.local/share/opencode/serve-logs/
EOF
}

main() {
    local cmd="${1:-start}"

    case "$cmd" in
        help|--help|-h)
            show_help
            exit 0
            ;;
        stop)
            stop_server
            exit 0
            ;;
        restart)
            stop_server
            ;;
        start)
            ;;
        *)
            echo "Unknown command: $cmd"
            show_help
            exit 1
            ;;
    esac

    mkdir -p "$DIR"

    nohup opencode serve --hostname 0.0.0.0 --port "$PORT" >"$LOGOUT" 2>"$LOGERR" &
    local pid=$!
    echo "$pid" > "$PIDFILE"

    echo "Started (PID: $pid) → http://0.0.0.0:$PORT"
    echo "Logs:   $LOGOUT, $LOGERR"
    echo "Stop:   ./opencode-serve.sh stop"
    echo "Restart: ./opencode-serve.sh restart"
}

main "$@"

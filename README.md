# P4-Bareflow

## Description

P4-Bareflow implements a *loop-free* L2 (Layer 2) learning bridge using P4 on a Barefoot Tofino switch.

## Documentation Index

- [Implemented Functionality](./docs/funcional.md): Functional explanation of what the system does.
- [Implementation](./docs/implementacion.md): Overview of how the system is implemented.
   - [P4 Code (Data Plane)](./docs/p4_dataplane.md): Details of the P4 program and its logic.
   - [Python Code (Controller)](./docs/python_controller.md): Explanation of the Python controller and how it works.

## Project Structure

```
p4-bareflow/
├── run.sh                     # Script to configure the SDE environment, compile P4, and start the switch
└── source/
    ├── tofino-libs/           # Library repository for working with Tofino hardware
    ├── controller/
    │   └── main.py            # Main Python controller code
    └── p4/
        └── p4_bareflow.p4     # P4 program for the Tofino switch
```

### Execution Scripts

- **`run.sh`**: Configures the Barefoot SDE environment, loads kernel modules, compiles the P4 program, and starts the switch daemon (`bf_switchd`).
- **`start_controller.sh`**: Runs the Python controller in a Docker container.

## Prerequisites

- **Hardware**: A compatible Barefoot Tofino switch.
- **Software**:
  - Barefoot SDE (Switch Development Environment) version 9.12.0 or compatible.
  - Docker to run the controller.
  - Python 3.8+ with the `bfrt_grpc` and `grpc` libraries.
- **Environment**: A Linux system with support for Barefoot kernel modules.

## Installation

1. **Clone the repository**:
   ```
   git clone <repo-url>
   cd p4-bareflow
   ```

2. **Configure the SDE environment**:
   - Make sure the SDE is installed in `/opt/bf-sde-9.12.0/`.
   - Run `run.sh` to configure the environment, compile P4, and start the switch.

3. **Build the controller's Docker image**:
   ```
   docker build -t p4-bareflow-controller .
   ```

## Usage

1. **Start the switch**:
   - Run `./run.sh` on the host. This will compile `p4_bareflow.p4` (note: the script mentions `switch-l2.p4`, but should point to `p4_bareflow.p4`).
   - Optionally, run `run_bfshell.sh` to configure ports manually.

2. **Run the controller**:
   - In a Docker container: `docker run p4-bareflow-controller`.
   - Or directly: `./start_controller.sh` (requires a configured Python environment).

3. **Monitoring**:
   - The controller logs activity according to the logging configuration.
   - Configured ports: 44-47 for hosts, 64 for the CPU.

## Environment Variables

- `GRPC_HOST`: gRPC server host (default: localhost).
- `GRPC_PORT`: gRPC port (default: 50052).
- `CLIENT_ID`: BF-RT client ID (default: 0).
- `DEVICE_ID`: Device ID (default: 0).
- `CPU_IFACE`: Linux interface for the CPU port (default: enp4s0f0).
- `LOG_LEVEL`: Logging level (DEBUG, INFO, etc.).

## Notes

- Make sure the switch's physical ports are connected correctly.
- For development, use the SDE in simulation mode if physical hardware is unavailable.

## Contributing

Contributions are welcome. Please open issues or pull requests in the repository.

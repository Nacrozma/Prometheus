"""eng - Prometheus's engineering laboratory (pure Python + numpy).

Modules (each documents its equations, assumptions and validity range):
    calibration   measured arm parameters with provenance (value, unit, method, equipment, uncertainty, date)
    hil           bench hardware-in-the-loop checks of the arm firmware (servo power disconnected)
    arm_dynamics  trajectories and recursive Newton-Euler joint torques for the 4-joint arm, servo limits
    arm_benchmark simulation-to-real accuracy benchmark: waypoint plans and error statistics from measurements
    structures    direct-stiffness 2-D truss and 2-D frame solvers
    machine       stress concentration, fatigue (Marin, Goodman, Soderberg), shafts, bolted joints
    optimize      design sweeps: mass vs safety factor vs deflection, Pareto front
    atmosphere    U.S. Standard Atmosphere 1976, 0-86 km geometric
    compressible  isentropic flow, normal and oblique shocks, Prandtl-Meyer expansion
    propulsion    ideal rocket nozzle performance (c*, CF, thrust, Isp)
    trajectory    planar 3-DOF point-mass trajectory, RK4
    control       discrete-time PID / state-feedback sandbox with noise, delay, saturation, rate limits
    uncertainty   GUM linear propagation, Monte Carlo, sensitivities, measurement statistics
    experiments   experiment records with provenance, data logger, re-run
    plots         dependency-free SVG plots
    report        engineering reports (Markdown, HTML, JSON, CSV, PDF)

Everything here is an educational and experimental engineering tool, not certified design software.
"""

MODEL_VERSION = "1.0.0"   # bump when any model's equations or defaults change (recorded in every experiment)


class EngError(ValueError):
    """Invalid engineering input: the message says what is wrong and, where possible, how to fix it."""

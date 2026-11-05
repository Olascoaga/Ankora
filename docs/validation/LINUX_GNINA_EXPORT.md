# Linux GNINA single-job export integration check

The predeclared `scripts/validate_linux_gnina_export.py` combines copies of the
preserved WSL CUDA job, its separately recorded pose analysis and its redocking
validation in a new isolated project. It requests a portable export and checks
safe ZIP member paths and byte-identical presence of inputs, poses, raw engine
output and records. It checks score-axis labels, the manifest and that neither
source changed. No scientific calculation is rerun. This is one-case
engineering evidence, not a scientific benchmark or native Linux acceptance.

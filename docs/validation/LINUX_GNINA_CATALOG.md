# GNINA result catalog engineering check

## Predeclared protocol

Copy the retained WSL GNINA CUDA API run `api-cuda-01` into a new isolated
directory. Do not rerun the scientific engine or modify that run's evidence.
Through the actual project-scoped HTTP API, find the retained GNINA result,
confirm its CNNscore/pK/energy fields match the authoritative job's first
recorded pose, fetch and hash-check every pose, and verify the score is not
placed in the kcal/mol field. Confirm Methods is explicitly unavailable. Move
the copied result to Trash and verify that the original project files remain
unchanged. Preserve a create-only evidence record on failure or success. This is
a WSL engineering check, not GUI, native workstation or scientific validation.

## Observed run: catalog-cuda-01

The copied real GNINA CUDA job appeared under its own scoring family. Its
recorded top-pose CNNscore, pK prediction and minimized affinity matched the
authoritative job; the kcal/mol summary was not used for CNNscore. Every pose
was fetched through the API and matched its recorded hash. Methods failed closed
and moving the copy to Trash left the original project and source evidence
unchanged. Evidence SHA-256:
`d8be9473600467d287dcd7f690b9ff4ef688e767c5f3557d303f1a0a45262948`.

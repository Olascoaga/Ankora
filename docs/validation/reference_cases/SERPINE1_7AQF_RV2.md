# SERPINE1 7AQF / RV2 frozen validation evidence

- Case: `SERPINE1_7AQF_RV2`
- Frozen on: `2026-08-28`
- Evidence SHA-256: `03d525417e7455dc40354648877a050675fdd8d5fcd1275c547fd007873cdd00`
- Verified records: `26`
- Verified artifacts: `54`
- Scope: Existing Ankora evidence for the exact recorded 7AQF receptor, crystallographic RV2 derivatives, co-crystal search space, Vina 1.2.7, AutoDock4 4.2.6 CPU, AutoDock-GPU 1.6, redocking, and pose-interaction records.

This file is generated from the adjacent case specification. It names exact
immutable records and verifies referenced artifact bytes; it does not rerun a
scientific tool or choose a preferred result.

## Record identities

| Role | Record | Identity | Record SHA-256 |
|---|---|---|---|
| structure.receptor_source | 7AQF source used for receptor and engine ligands | `76f5afae-1f5d-4baa-8359-a7335407abb8` | `ced6a1515f54d3fe02880c0f37adfb33b500b65a49da2588fcdfe789a410a49c` |
| structure.reference_source | Independent 7AQF import used for the reference ligand | `90dfd005-25b7-442b-bd0d-1356ee2af1d3` | `8d0a181097566fb8fc439713b15c5d24ee7491451c742060fce662a0ec83f894` |
| receptor.docking_ready | Prepared receptor shared by the frozen engine records | `72ff70a2-b373-4f59-b162-5bbc3a471b6e` | `81e89d848d00296cc7ddd21a589ad7ea9cf5199068b3b748ecced5f6fabc0721` |
| ligand.crystal_reference | Crystallographic RV2 used by redocking RMSD | `12ebd97c-4302-4e0f-ad49-9b606edab666` | `7efa917af38cb60c01f7f790102b70df2acb94305112843fbeaeaf3f00d96e12` |
| ligand.vina_original | RV2 extraction used for Vina | `fa7e1bea-6f57-486f-a98a-e348c58cda4b` | `3dcb1944054ef96e536cc7a03ef37ecd70d40c33a4e798658551b514d4095bbd` |
| ligand.vina_state | Explicit pH 7.4 RV2 state used for Vina | `1b02d9b6-53c0-4457-ac23-bd1f3246437e` | `491610efb53cea1a2ffc588c0ccad65306eabfeb1441c2cccf7e5d6e8af8c3a3` |
| ligand.vina_conformer | Independent minimized RV2 conformer used for Vina | `097feb6a-6a25-4fa6-b2d6-a96e18a6008c` | `6a1306191a05ac3906ba87dd5f9b79ad00647a0874fa35e5b7911e37d3295611` |
| ligand.vina_pdbqt | Meeko RV2 input used for Vina | `4021fc7d-a8e4-492b-8815-b2e30f9ca880` | `e74a51250c642cdabbe527937426a9a3d1bbad1aa6330cc1bef14bcde21b1f84` |
| binding_site.vina | Co-crystal box used for Vina | `b946e1d6-af18-431c-9fb0-a25891dda40d` | `9dfba6bbdf426122876bcdf596d78b0bd6dc9fe43046018242458ea66c6ee093` |
| docking.vina | Vina RV2 single-ligand job preserved in recoverable Trash | `ccb42404-e1ce-44a7-8fd6-71b1d2b38959` | `2b0661a11487612fd0530656a53eb78e6f9d80ad3134384e86b497013d8d7652` |
| interaction.vina_top_pose | ProLIF analysis of the exact Vina top pose | `59ad4103-fb7a-4754-9188-ed2e79112a00` | `cd86e37d44678d27f3e6ccfd65c62adfa4224f8316c0afba8169eef32df55fc8` |
| ligand.cpu_original | RV2 extraction used for AutoDock4 CPU | `b6da69d4-558a-494d-a7e3-243b06a89024` | `e37d20ad8bcb403ed1e7debe7d24742e6ed8e4900e7df1d09a3a7e2c16c01e67` |
| ligand.cpu_conformer | Neutral minimized RV2 conformer used for AutoDock4 CPU | `5c7cf0e1-0d3d-476c-94b8-97e250bd3535` | `1f4ab6f0e53bc1444cc818549729b246b60b486592f957751a5697a1785fbfcb` |
| ligand.cpu_pdbqt | Meeko neutral RV2 input used for AutoDock4 CPU | `c5002724-b9b5-4d0a-b762-b96ebf0f1a02` | `8142b4c91e523ad935b0256aa0b31e692d974bb5f2ceb6c9e460a259e2e09674` |
| binding_site.cpu | Co-crystal box recorded for AutoDock4 CPU | `4a839b60-46f5-47b9-92bb-16f4d3703874` | `e93b677f0fd443a644378edf10b220c37d55b714f618d108ea2e4a0e80ce3340` |
| maps.shared_autogrid | AutoGrid map set reused by CPU and GPU | `96bffc5a-6e5e-4d29-80ec-5a51a6c7e58b` | `1539549f41a714d3f8f0b27a08e34c1687e231a04c2ceb1bd1299d0f6350e0fe` |
| docking.autodock4_cpu | AutoDock4 CPU RV2 job judged by redocking | `bdef5443-02c1-4d67-9ea9-d6f32e8a9890` | `f6937bbb115e984140c2704c5b664904118a4513065728e70530110676e8fc6d` |
| redocking.autodock4_cpu | In-place symmetry-aware RMSD verdict for CPU | `179484ac-a6cd-497c-8147-1333955813ff` | `25e4997eb79cef84e0fe4e7f0d103c45192edf154b4ae091a0a02c1388469a40` |
| interaction.autodock4_cpu_run1 | ProLIF analysis of exact CPU run 1 (not top-ranked) | `4e0e6a5e-3cb2-4f15-af70-84e9c9dae398` | `64c6cd12453ed6cc972c1d14c517cce4b82629bf7255af468f8ac84cb475ee17` |
| ligand.gpu_original | RV2 extraction used for AutoDock-GPU | `7a65023d-418e-450a-9dbd-a390334bf377` | `5268add9b04c306ec3256e05a58cbf17b843488bbe92f82954a3668c4cc9f3db` |
| ligand.gpu_state | Explicit pH 7.4 RV2 state used for AutoDock-GPU | `cb88050b-d4f4-442d-aad4-00d35959a233` | `000c9117ac648631f57c3dcc9262e64dd09c312ec8d4e1d700b90a2a374f9023` |
| ligand.gpu_conformer | Independent minimized RV2 conformer used for AutoDock-GPU | `445fbd04-1d43-4b80-be62-f46cbe7f2623` | `03639437362d18221ff1b361ed28cac9b04608910396dbeb71cfcf61eb679a31` |
| ligand.gpu_pdbqt | Meeko anionic RV2 input used for AutoDock-GPU | `3b0d4589-d711-4aa7-a34b-a62bb817b24d` | `2493907ea2fd1adfbf8545d01c6dcc66719236b07552e62d535d3ead2bbee098` |
| binding_site.gpu | Co-crystal box recorded for AutoDock-GPU | `5f27a393-ce10-4b61-a884-3d4ea842b638` | `22e4be64f72c0bea9e3cae9ea451db4e30dfce45172b87fd6852cb21b4748cf7` |
| docking.autodock_gpu | AutoDock-GPU RV2 job judged by redocking | `d6cfdfd8-ac07-48f9-bc16-c3982ebe6d94` | `11973816e0e58bcb29b8ccb3d70cf7af553858b679b2a228ade535df207ab7a6` |
| redocking.autodock_gpu | In-place symmetry-aware RMSD verdict for GPU | `58954905-324e-4c61-9766-ad6c18b77d6d` | `7d820ffc128019349a89614524695ad81fa258cdcc67f6b1ee3720667ec074df` |

## Scientific matrix

| Role | Field | Recorded value |
|---|---|---|
| structure.receptor_source | PDB entry | 7AQF |
| structure.receptor_source | Experimental method | X-RAY DIFFRACTION |
| structure.receptor_source | Resolution (Å) | 1.77 |
| structure.receptor_source | Models | 1 |
| structure.receptor_source | Atoms | 6266 |
| structure.receptor_source | Residues | 1218 |
| structure.receptor_source | Missing residues | 22 |
| structure.receptor_source | Missing atoms | 123 |
| structure.reference_source | PDB entry | 7AQF |
| structure.reference_source | Source URI | https://files.rcsb.org/download/7AQF.cif |
| structure.reference_source | Deposited SHA-256 | 79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac |
| receptor.docking_ready | Source structure | 76f5afae-1f5d-4baa-8359-a7335407abb8 |
| receptor.docking_ready | Status | docking_ready |
| receptor.docking_ready | Selected chains | ["A"] |
| receptor.docking_ready | Water action | remove |
| receptor.docking_ready | Component decisions | [{"action": "remove", "component_id": "ligand\|A\|RV2\|401\|"}] |
| receptor.docking_ready | Reference component | ligand\|A\|RV2\|401\| |
| receptor.docking_ready | Relaxation | {"enabled": true, "max_iterations": 200, "restraint_force_constant_kcal_mol_a2": 50.0} |
| receptor.docking_ready | Protonation | {"enabled": true, "force_field": "AMBER", "ph": 7.4} |
| receptor.docking_ready | Recorded outputs | 6 |
| ligand.crystal_reference | Source structure | 90dfd005-25b7-442b-bd0d-1356ee2af1d3 |
| ligand.crystal_reference | Locator | {"chain_id": "A", "component_name": "RV2", "insertion_code": "", "sequence_number": 401} |
| ligand.crystal_reference | Formula | C19H13ClN2O5 |
| ligand.crystal_reference | Formal charge | 0 |
| ligand.crystal_reference | Heavy atoms | 27 |
| ligand.crystal_reference | Molecular weight (g/mol) | 384.7750000000001 |
| ligand.vina_original | Source structure | 76f5afae-1f5d-4baa-8359-a7335407abb8 |
| ligand.vina_original | Original SHA-256 | 6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4 |
| ligand.vina_original | Formula | C19H13ClN2O5 |
| ligand.vina_original | Formal charge | 0 |
| ligand.vina_state | Parent state | a0714c3c-76aa-4c30-835b-f9ef8782f70d |
| ligand.vina_state | Formula | C19H12ClN2O5- |
| ligand.vina_state | Formal charge | -1 |
| ligand.vina_state | Selection | {"candidate_count": 1, "candidate_index": 0, "ph_max": 7.4, "ph_min": 7.4, "precision": 1.0} |
| ligand.vina_state | Tool version | 2.0.2 |
| ligand.vina_conformer | Formula | C19H12ClN2O5- |
| ligand.vina_conformer | Formal charge | -1 |
| ligand.vina_conformer | Embedding | ETKDGv3 |
| ligand.vina_conformer | Force field | MMFF94s |
| ligand.vina_conformer | Random seed | 20260819 |
| ligand.vina_conformer | Selected conformer | 4 |
| ligand.vina_conformer | Final MMFF energy (kcal/mol) | 49.21192227209204 |
| ligand.vina_pdbqt | Conformer | 097feb6a-6a25-4fa6-b2d6-a96e18a6008c |
| ligand.vina_pdbqt | Charge model | gasteiger |
| ligand.vina_pdbqt | Tool | {"name": "Meeko ligand preparation", "version": "0.7.1"} |
| ligand.vina_pdbqt | PDBQT SHA-256 | 760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69 |
| binding_site.vina | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| binding_site.vina | Source | co_crystallized_ligand |
| binding_site.vina | Ligand origin | {"heterogen": {"chain_id": "A", "insertion_code": "", "residue_name": "RV2", "sequence_number": 401}, "padding_angstrom": 5.0} |
| binding_site.vina | Box | {"center_x": 35.4305, "center_y": -2.967, "center_z": -0.7905, "size_x": 21.596999999999998, "size_y": 19.87, "size_z": 19.317} |
| binding_site.vina | Stale | false |
| docking.vina | Status | completed |
| docking.vina | Tool | {"name": "AutoDock Vina", "version": "1.2.7"} |
| docking.vina | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| docking.vina | Binding site | b946e1d6-af18-431c-9fb0-a25891dda40d |
| docking.vina | Ligand | fa7e1bea-6f57-486f-a98a-e348c58cda4b |
| docking.vina | Ligand preparation | 4021fc7d-a8e4-492b-8815-b2e30f9ca880 |
| docking.vina | Parameters | {"cpu_threads": 15, "energy_range_kcal_mol": 3.0, "exhaustiveness": 8, "min_rmsd_angstrom": 1.0, "num_modes": 9, "seed": 20260823, "timeout_minutes": 360} |
| docking.vina | Pose count | 9 |
| docking.vina | Top Vina score (kcal/mol) | -7.073 |
| interaction.vina_top_pose | Catalog result | vina_job:ccb42404-e1ce-44a7-8fd6-71b1d2b38959 |
| interaction.vina_top_pose | Pose artifact | ccb42404-e1ce-44a7-8fd6-71b1d2b38959-pose-1 |
| interaction.vina_top_pose | Pose SHA-256 | 350b4a21f35df6aa9143dab3170c5078f3aacb31e5b08c6a6b5e4021c29baccc |
| interaction.vina_top_pose | Detector | {"name": "ProLIF", "version": "2.2.1"} |
| interaction.vina_top_pose | Profile | {"interactions": ["Hydrophobic", "HBDonor", "HBAcceptor", "FaceToFace", "EdgeToFace", "CationPi", "PiCation", "Anionic", "Cationic", "XBAcceptor", "XBDonor", "MetalAcceptor", "MetalDonor"], "profile_id": "ankora-default-v1", "vicinity_cutoff_angstrom": 6.0} |
| interaction.vina_top_pose | Geometric contacts | 17 |
| ligand.cpu_original | Source structure | 76f5afae-1f5d-4baa-8359-a7335407abb8 |
| ligand.cpu_original | Original SHA-256 | 6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4 |
| ligand.cpu_original | Formula | C19H13ClN2O5 |
| ligand.cpu_original | Formal charge | 0 |
| ligand.cpu_conformer | Formula | C19H13ClN2O5 |
| ligand.cpu_conformer | Formal charge | 0 |
| ligand.cpu_conformer | Embedding | ETKDGv3 |
| ligand.cpu_conformer | Force field | MMFF94s |
| ligand.cpu_conformer | Random seed | 20260819 |
| ligand.cpu_conformer | Selected conformer | 11 |
| ligand.cpu_conformer | Final MMFF energy (kcal/mol) | 45.402079417259785 |
| ligand.cpu_pdbqt | Conformer | 5c7cf0e1-0d3d-476c-94b8-97e250bd3535 |
| ligand.cpu_pdbqt | Charge model | gasteiger |
| ligand.cpu_pdbqt | Tool | {"name": "Meeko ligand preparation", "version": "0.7.1"} |
| ligand.cpu_pdbqt | PDBQT SHA-256 | e8da59c573890ca0a65b4b5503e54d0cd72815c612d0d72fdbeeba1d4cdb3830 |
| binding_site.cpu | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| binding_site.cpu | Source | co_crystallized_ligand |
| binding_site.cpu | Box | {"center_x": 35.4305, "center_y": -2.967, "center_z": -0.7905, "size_x": 21.596999999999998, "size_y": 19.87, "size_z": 19.317} |
| binding_site.cpu | Stale | false |
| maps.shared_autogrid | Identity key | e45fe46d86fa6f09016e2d280d0f57381b88a13f3894af88c656ac36e2fbba60 |
| maps.shared_autogrid | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| maps.shared_autogrid | Receptor SHA-256 | 83379bb5f78dcebc64df92e8b50c35bb81879913dc01e36024517a2be4604da0 |
| maps.shared_autogrid | Recorded binding site | b9620e02-bcaf-415c-a9b5-8c72cb768596 |
| maps.shared_autogrid | Box | {"center_x": 35.4305, "center_y": -2.967, "center_z": -0.7905, "size_x": 21.596999999999998, "size_y": 19.87, "size_z": 19.317} |
| maps.shared_autogrid | Realized grid geometry | {"npts": [58, 54, 52], "realized_size_angstrom": [21.75, 20.25, 19.5], "requested_size_angstrom": [21.596999999999998, 19.87, 19.317], "spacing_angstrom": 0.375} |
| maps.shared_autogrid | AutoGrid | {"name": "AutoGrid", "version": "4.2.6"} |
| maps.shared_autogrid | AutoGrid executable SHA-256 | 797efce687d1ae82df59726461e0e1966b3d8edb0f8b187f982fa1ab0c12da9e |
| maps.shared_autogrid | Successful completion logged | true |
| docking.autodock4_cpu | Status | completed |
| docking.autodock4_cpu | AutoDock | {"name": "AutoDock", "version": "4.2.6"} |
| docking.autodock4_cpu | Executable SHA-256 | 36c0b16c04d7df8e6225737bae65bb04058d1f4c90accfaf2d230dbc913954bf |
| docking.autodock4_cpu | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| docking.autodock4_cpu | Binding site | 4a839b60-46f5-47b9-92bb-16f4d3703874 |
| docking.autodock4_cpu | Map set | 96bffc5a-6e5e-4d29-80ec-5a51a6c7e58b |
| docking.autodock4_cpu | Ligand preparation | c5002724-b9b5-4d0a-b762-b96ebf0f1a02 |
| docking.autodock4_cpu | Ligand PDBQT SHA-256 | e8da59c573890ca0a65b4b5503e54d0cd72815c612d0d72fdbeeba1d4cdb3830 |
| docking.autodock4_cpu | Parameters | {"cluster_rmsd_tolerance_angstrom": 2.0, "ga_energy_evaluations": 2500000, "ga_generations": 27000, "ga_population_size": 150, "ga_runs": 10, "seed_1": 20260824, "seed_2": 20260824, "timeout_minutes": 360} |
| docking.autodock4_cpu | Runs | 10 |
| docking.autodock4_cpu | Top binding energy (kcal/mol) | -4.96 |
| redocking.autodock4_cpu | Reference case | SERPINE1_7AQF_RV2 |
| redocking.autodock4_cpu | Source result | bdef5443-02c1-4d67-9ea9-d6f32e8a9890 |
| redocking.autodock4_cpu | Engine | AutoDock |
| redocking.autodock4_cpu | Engine version | 4.2.6 |
| redocking.autodock4_cpu | Reference ligand | 12ebd97c-4302-4e0f-ad49-9b606edab666 |
| redocking.autodock4_cpu | Reference SHA-256 | 6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4 |
| redocking.autodock4_cpu | Bitwise reproducible | true |
| redocking.autodock4_cpu | Metrics | {"best_overall_rmsd_angstrom": 0.45351956958878875, "best_top5_rmsd_angstrom": 0.4897538308322, "first_recovering_rank": 2, "outcome": "recovered_but_misranked", "pose_count": 10, "ranking_success": false, "recovered_pose_count": 6, "sampling_success": true, "threshold_angstrom": 2.0, "top1_rmsd_angstrom": 3.139145661080651} |
| interaction.autodock4_cpu_run1 | Catalog result | autodock4_job:bdef5443-02c1-4d67-9ea9-d6f32e8a9890 |
| interaction.autodock4_cpu_run1 | Pose artifact | ab80593f-3881-46f6-9e3b-226cf2f03cf6 |
| interaction.autodock4_cpu_run1 | Pose label | Cluster 1 · run 1 |
| interaction.autodock4_cpu_run1 | Pose SHA-256 | 4ab33f193ab53d6789e375b22ceda58dfccd2258f5ecda4c4678a4444f90f559 |
| interaction.autodock4_cpu_run1 | Detector | {"name": "ProLIF", "version": "2.2.1"} |
| interaction.autodock4_cpu_run1 | Geometric contacts | 33 |
| ligand.gpu_original | Source structure | 76f5afae-1f5d-4baa-8359-a7335407abb8 |
| ligand.gpu_original | Original SHA-256 | 6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4 |
| ligand.gpu_original | Formula | C19H13ClN2O5 |
| ligand.gpu_original | Formal charge | 0 |
| ligand.gpu_state | Parent state | 1ed26c4f-a363-4129-8bae-760879887fa8 |
| ligand.gpu_state | Formula | C19H12ClN2O5- |
| ligand.gpu_state | Formal charge | -1 |
| ligand.gpu_state | Selection | {"candidate_count": 1, "candidate_index": 0, "ph_max": 7.4, "ph_min": 7.4, "precision": 1.0} |
| ligand.gpu_state | Tool version | 2.0.2 |
| ligand.gpu_conformer | Formula | C19H12ClN2O5- |
| ligand.gpu_conformer | Formal charge | -1 |
| ligand.gpu_conformer | Embedding | ETKDGv3 |
| ligand.gpu_conformer | Force field | MMFF94s |
| ligand.gpu_conformer | Random seed | 20260819 |
| ligand.gpu_conformer | Selected conformer | 4 |
| ligand.gpu_conformer | Final MMFF energy (kcal/mol) | 49.21192227209204 |
| ligand.gpu_pdbqt | Conformer | 445fbd04-1d43-4b80-be62-f46cbe7f2623 |
| ligand.gpu_pdbqt | Charge model | gasteiger |
| ligand.gpu_pdbqt | Tool | {"name": "Meeko ligand preparation", "version": "0.7.1"} |
| ligand.gpu_pdbqt | PDBQT SHA-256 | 760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69 |
| binding_site.gpu | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| binding_site.gpu | Source | co_crystallized_ligand |
| binding_site.gpu | Box | {"center_x": 35.4305, "center_y": -2.967, "center_z": -0.7905, "size_x": 21.596999999999998, "size_y": 19.87, "size_z": 19.317} |
| binding_site.gpu | Stale | false |
| docking.autodock_gpu | Status | completed |
| docking.autodock_gpu | AutoDock-GPU | {"name": "AutoDock-GPU", "version": "1.6"} |
| docking.autodock_gpu | Executable SHA-256 | be21dd5dea36a391e3d77286cd8a5bf18b080306d32c7178c56f0a9e4f373bbf |
| docking.autodock_gpu | Device | NVIDIA GeForce RTX 5050 Laptop GPU |
| docking.autodock_gpu | Bitwise reproducible | false |
| docking.autodock_gpu | Receptor | 72ff70a2-b373-4f59-b162-5bbc3a471b6e |
| docking.autodock_gpu | Binding site | 5f27a393-ce10-4b61-a884-3d4ea842b638 |
| docking.autodock_gpu | Map set | 96bffc5a-6e5e-4d29-80ec-5a51a6c7e58b |
| docking.autodock_gpu | Ligand preparation | 3b0d4589-d711-4aa7-a34b-a62bb817b24d |
| docking.autodock_gpu | Ligand PDBQT SHA-256 | 760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69 |
| docking.autodock_gpu | Parameters | {"autostop": false, "cluster_rmsd_tolerance_angstrom": 2.0, "device_number": 1, "energy_evaluations": 2500000, "heuristics": false, "local_search_method": "ad", "population_size": 150, "runs": 10, "seed_1": 20260826, "seed_2": 20260826, "seed_3": 20260826, "timeout_minutes": 60} |
| docking.autodock_gpu | Runs | 10 |
| docking.autodock_gpu | Top binding energy (kcal/mol) | -5.7 |
| redocking.autodock_gpu | Reference case | SERPINE1_7AQF_RV2 |
| redocking.autodock_gpu | Source result | d6cfdfd8-ac07-48f9-bc16-c3982ebe6d94 |
| redocking.autodock_gpu | Engine | AutoDock-GPU |
| redocking.autodock_gpu | Engine version | 1.6 |
| redocking.autodock_gpu | Reference ligand | 12ebd97c-4302-4e0f-ad49-9b606edab666 |
| redocking.autodock_gpu | Reference SHA-256 | 6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4 |
| redocking.autodock_gpu | Bitwise reproducible | false |
| redocking.autodock_gpu | Metrics | {"best_overall_rmsd_angstrom": 1.3307721094941114, "best_top5_rmsd_angstrom": 1.3307721094941114, "first_recovering_rank": 2, "outcome": "recovered_but_misranked", "pose_count": 10, "ranking_success": false, "recovered_pose_count": 9, "sampling_success": true, "threshold_angstrom": 2.0, "top1_rmsd_angstrom": 10.717198780637771} |
| redocking.autodock_gpu | Warnings | [{"code": "DOCKING_MAPS_FROM_EQUIVALENT_SITE", "details": {"map_set_binding_site_id": "b9620e02-bcaf-415c-a9b5-8c72cb768596", "requested_binding_site_id": "5f27a393-ce10-4b61-a884-3d4ea842b638"}, "message": "These maps were generated for a different binding-site record with an identical receptor and search space, so they apply unchanged to this one.", "recoverable": true, "stage": "autodock_gpu_docking"}, {"code": "DOCKING_BACKEND_NOT_REPRODUCIBLE", "details": {"measured_spread_kcal_mol": 0.13, "repeats": 6}, "message": "AutoDock-GPU does not reproduce a run from its seed. Repeating this job with these exact inputs will give slightly different energies and a different cluster structure. The AutoDock4 CPU backend is bit-identical across repeats if an exactly reproducible result is required.", "recoverable": true, "stage": "autodock_gpu_docking"}] |

## Verified artifacts

| Role | Artifact | Bytes | SHA-256 |
|---|---|---:|---|
| structure.receptor_source | Deposited 7AQF mmCIF | 698639 | `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac` |
| structure.reference_source | Second immutable 7AQF mmCIF import | 698639 | `79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac` |
| receptor.docking_ready | Selected receptor PDB | 244377 | `62987da61fe858e579a9dc85d1aac94258e9e13cee40117b681aac88f171cae6` |
| receptor.docking_ready | Repaired receptor PDB | 238940 | `06913afbaa9dca42ebede1151f305b2e00d619ca0fa3d299e887cf96104c4f97` |
| receptor.docking_ready | Relaxed receptor PDB | 238940 | `fd6beba9054d96dca8df37860ab1d28792dae59e0181d392b96311cd82350ec3` |
| receptor.docking_ready | Protonated receptor PQR | 418127 | `8be0def7f1f9f95335224ce48a131bbffde6080805f7b5c91e811a555c3f888a` |
| receptor.docking_ready | Protonated receptor PDB | 482906 | `3fc201d458eeed347fd498d3173a0a1e8ae487c918f7669769b09c1223371799` |
| receptor.docking_ready | Docking receptor PDBQT | 289575 | `83379bb5f78dcebc64df92e8b50c35bb81879913dc01e36024517a2be4604da0` |
| ligand.crystal_reference | Observed crystallographic RV2 SDF | 2348 | `6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4` |
| ligand.vina_original | Vina-lineage crystallographic RV2 SDF | 2348 | `6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4` |
| ligand.vina_state | Vina-lineage explicit protonation state | 2366 | `bdbefc5627a422a32666a9b0841f90e3fd6b1f29a40056ca0082d4766a2620e5` |
| ligand.vina_conformer | Vina-lineage minimized conformer | 3362 | `8e0dc4618ef37456d064ecc5493d8b47eeeacb83d9e79b61b19d0edc9b7d6708` |
| ligand.vina_pdbqt | Vina RV2 PDBQT | 2846 | `760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69` |
| docking.vina | Vina top pose | 3121 | `350b4a21f35df6aa9143dab3170c5078f3aacb31e5b08c6a6b5e4021c29baccc` |
| ligand.cpu_original | CPU-lineage crystallographic RV2 SDF | 2348 | `6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4` |
| ligand.cpu_conformer | CPU-lineage neutral minimized conformer | 3427 | `34adf54c631de34cf3d57c8c6b426a12ecf18053a3336071c148850ba245f48a` |
| ligand.cpu_pdbqt | AutoDock4 CPU RV2 PDBQT | 2965 | `e8da59c573890ca0a65b4b5503e54d0cd72815c612d0d72fdbeeba1d4cdb3830` |
| maps.shared_autogrid | A map | 1382427 | `21df914a4fca2682302342b8919067227f75f6c35dac8d5469ea18592c69b509` |
| maps.shared_autogrid | C map | 1386217 | `71ed0945b7ab5846183f39b6948df284c27a2a0744b22f453f11bbf0122bb665` |
| maps.shared_autogrid | Cl map | 1402792 | `806807d5fe6f937072445e729030c978037dde9c83abecc31f6cb317ba22fb83` |
| maps.shared_autogrid | HD map | 1260240 | `c8eec36373bce5df74c7dd1f0c93c1dd96adc3cd3977e1c681054a91c1337111` |
| maps.shared_autogrid | N map | 1369422 | `cb05754ec32615496b4b5da0e1dffad83a81d07fdc56e7309c14f07ef5f0fcbc` |
| maps.shared_autogrid | OA map | 1365438 | `a8fa4252fd4b5f0f7fc0e6145c70d66d30914af8b12733d58053885ea23cc58f` |
| maps.shared_autogrid | Desolvation map | 1141918 | `a9bdeb78c84b436b4bec70749a9fd4a8a0e8d541056505b2105f07af421e6ce5` |
| maps.shared_autogrid | Electrostatic map | 1245642 | `1ae09524af0ae9770a0e6b16fca35c4790bb8fe372225dc61964aa74dc143c80` |
| maps.shared_autogrid | AutoGrid log | 460890 | `b94e511fb3525337cb1c0ac6199ca1865898cef429feebbdb5065d17d11f0aa2` |
| maps.shared_autogrid | Grid parameter file | 367 | `c4e70685a4da47d5a472ab7b4fde8653ab623f760177364d778bdc549f26fa6d` |
| maps.shared_autogrid | Field file | 1736 | `444e39e22816c265c704419e8e77dc872f954da1f6195f843234deac4c8dee4c` |
| maps.shared_autogrid | Grid origin | 45 | `489e336b78a22f82c73bddbed0a620a463c7b00f42a444df8c598e6a9a4e1509` |
| maps.shared_autogrid | Map-set receptor PDBQT | 289575 | `83379bb5f78dcebc64df92e8b50c35bb81879913dc01e36024517a2be4604da0` |
| docking.autodock4_cpu | CPU run 1 | 4152 | `4ab33f193ab53d6789e375b22ceda58dfccd2258f5ecda4c4678a4444f90f559` |
| docking.autodock4_cpu | CPU run 2 | 4151 | `779f21b7e452554e3e4a50f02ae26e331f58a957b97b3925b9e0be93d714add0` |
| docking.autodock4_cpu | CPU run 3 | 4154 | `3444a1e0816e6d28869e5b604809d8e7b117c900d64cad7d03375e5e1951f900` |
| docking.autodock4_cpu | CPU run 4 | 4161 | `7fa4e3f412cd41f9de241ffd144898dd602556ebcc14471075f1c3b9ff2cbd66` |
| docking.autodock4_cpu | CPU run 5 | 4146 | `cead2658dcd88c13763d6cdb7e93e8accd20ce705b956d9179176b1a4d09bf2c` |
| docking.autodock4_cpu | CPU run 6 | 4151 | `e60656df43d8aa87eff44dcdbed8124ea41238771cd23433242cfb67e8905c5f` |
| docking.autodock4_cpu | CPU run 7 | 4154 | `7753d14f2a7c4f11db9bcdf6af71fdc2cbd9d17e5b13832a8cbdf1ad123545ed` |
| docking.autodock4_cpu | CPU run 8 | 4158 | `8267a92b6297e661865e49700910fc412b25b522bae016f9a5d8150fb84d06a2` |
| docking.autodock4_cpu | CPU run 9 | 4148 | `dae4f4e240103eb016d7c58478e49881e727d5843f5743aa5dacc30ee1ce38b5` |
| docking.autodock4_cpu | CPU run 10 | 4155 | `4b855971bf8a5310ac4d5922c9ad24e65de6bc99584e76584bc9fec3d200bbd2` |
| ligand.gpu_original | GPU-lineage crystallographic RV2 SDF | 2348 | `6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4` |
| ligand.gpu_state | GPU-lineage explicit protonation state | 2366 | `bdbefc5627a422a32666a9b0841f90e3fd6b1f29a40056ca0082d4766a2620e5` |
| ligand.gpu_conformer | GPU-lineage anionic minimized conformer | 3362 | `8e0dc4618ef37456d064ecc5493d8b47eeeacb83d9e79b61b19d0edc9b7d6708` |
| ligand.gpu_pdbqt | AutoDock-GPU RV2 PDBQT | 2846 | `760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69` |
| docking.autodock_gpu | GPU run 1 | 3632 | `98c3115d5d0b9514a9a3dfa1a7e8faf7f851bb560d6123d9a2560f79f1d18ace` |
| docking.autodock_gpu | GPU run 2 | 3632 | `983d695e4e9477cc8b88518a10aa10f5372822944ac5355dd8df93bf0b9868f0` |
| docking.autodock_gpu | GPU run 3 | 3632 | `1c58d33cb348434908517151bae6c64a15d3ca9b42f198110b91158e9e1cb092` |
| docking.autodock_gpu | GPU run 4 | 3632 | `f3cf6e6dc21cd308c3a3e93b66195b7f003111c12052a366c8ef9ee67daf9c6d` |
| docking.autodock_gpu | GPU run 5 | 3632 | `376f3d85281e878ef2cc83e63975d7434bf171572dffa1a1f0830154b0eab081` |
| docking.autodock_gpu | GPU run 6 | 3632 | `6d6eef88b7f11f0eadda2b9be3d94f35c06addc2aff19602c8a029d3e72055c7` |
| docking.autodock_gpu | GPU run 7 | 3632 | `61463e602cad199123f38b3d04dad470b743b2aaa27dcfaac9a06c8196e7bd6c` |
| docking.autodock_gpu | GPU run 8 | 3632 | `1f65409a2d3fb6633af6c763157f511aa397a4fc800ca27fa3fbd528e50bdd0f` |
| docking.autodock_gpu | GPU run 9 | 3632 | `46d7d83f6472330cbf64df17ed1307bbbb7ce41b8550e9cc49b2070ec58987a9` |
| docking.autodock_gpu | GPU run 10 | 3634 | `e25cc3751050be6d4a0ebaba5bb9b41c32f18ab029aa296ed052d2f2676d4c5b` |

## Interpretation

- The two imported 7AQF mmCIF artifacts are byte-identical (SHA-256 79fd3b96adca6bdbe17ded6e9c693534007ae2cb0538739044788754b7c6faac); the four crystallographic RV2 SDF records are also byte-identical (SHA-256 6fa65e2d76adb3ba91d60a5747e4986d359766c965f29fdf3559203f26195fe4). Independent record IDs are provenance identities, not different deposited molecules.
- All three docking records use receptor 72ff70a2-b373-4f59-b162-5bbc3a471b6e and numerically equivalent co-crystal boxes: center (35.4305, -2.967, -0.7905) Å and size (21.597, 19.87, 19.317) Å. AutoDock4 CPU and GPU reuse the same verified AutoGrid map-set identity.
- The prepared ligand state is not controlled across all engines. AutoDock4 CPU used a neutral C19H13ClN2O5 conformer and PDBQT e8da59c573890ca0a65b4b5503e54d0cd72815c612d0d72fdbeeba1d4cdb3830. Vina and AutoDock-GPU used the explicitly selected anion C19H12ClN2O5- and the same PDBQT 760f3a289dd45e02ba71c6f04d66dd03c0cfaa6cc0873531fe562ea388cffc69. Their individual records remain valid, but this set is not a same-chemical-state CPU/GPU comparison.
- AutoDock4 CPU sampled a crystallographic-like pose (best overall 0.454 Å; first recovering rank 2) but ranked a 3.139 Å pose first. AutoDock-GPU also sampled one (best overall 1.331 Å; first recovering rank 2) but ranked a 10.717 Å pose first. Both exact records therefore report recovered_but_misranked at the recorded 2.0 Å threshold.
- The Vina record reports nine modes and a top score of -7.073 kcal/mol. Its per-mode RMSD bounds are relative to Vina's best mode, not to crystallographic RV2, so they provide no redocking sampling or ranking verdict.
- The Vina top-pose and AutoDock4 CPU run-1 ProLIF records contain 17 and 33 geometric contacts respectively. They describe only those exact poses under the recorded profile; they are neither affinity measurements nor evidence that one engine is biologically superior.
- The selected Vina job and its interaction analysis are recoverable Trash records. Their source bytes and operation provenance remain present, but they are intentionally absent from the active Results catalog.

## Known gaps

- No structured in-place crystallographic RMSD validation exists for the Vina RV2 job, so Vina sampling and ranking cannot yet be claimed.
- No M9 pose-interaction record exists for an exact pose from the frozen AutoDock-GPU RV2 job.
- The CPU and GPU redocking inputs differ in ligand protonation/charge and minimized-conformer bytes; a controlled backend comparison requires a newly frozen common chemical state before execution.
- The current evidence is one SERPINE1/7AQF system and does not establish transferability. The independent PIK3CD 6OCO/M5V case must be frozen before docking and completed before reference-grade claims.
- The older placeholder box center (35.561, -4.298, -0.660) Å and size (12.585, 10.101, 11.617) Å are not the box used by these frozen runs and are superseded for this evidence set.

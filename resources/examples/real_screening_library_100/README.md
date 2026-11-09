# Biblioteca de demostración: 100 estructuras reales

Esta biblioteca contiene las primeras 100 entradas, en su orden original, del archivo público [Data/NCI/first_5K.smi de RDKit, versión 2025.09.6](https://github.com/rdkit/rdkit/blob/Release_2025_09_6/Data/NCI/first_5K.smi). Son estructuras del conjunto de ejemplo NCI distribuido con RDKit; no fueron inventadas ni seleccionadas en función de los resultados de los filtros. Los números son las etiquetas tal como aparecen en la fuente: aquí no se afirma que sean identificadores NSC verificados.

- `nci_real_100.sdf`: las 100 moléculas, con nombres, etiqueta y SMILES originales. Contiene coordenadas **2D**, útiles para representación; no son conformadores 3D minimizados.
- `nci_real_100.smi`: copia literal de las primeras 100 líneas de la fuente.
- `resultados_filtros.csv`: decisiones y descriptores por molécula para los dos perfiles indicados abajo. Un campo vacío para un compuesto pendiente de decisión significa **no evaluado**, no ausencia de alertas.
- `manifest.json`: planes, conteos, versiones y hashes para reproducir la comprobación.

SHA-256 de la fuente completa: `91e71c015f14939837f2943dcc904f7c87e5a3a0124d82b05c28ad2f23004def`. SHA-256 de las primeras 100 líneas: `7230041129c4433e2264199eba52ccb29a8c7b225c6b404e9ec21b18671ebd4d`.

El archivo `RDKIT-LICENSE.txt` conserva el aviso de licencia distribuido por RDKit. `build_library.py` reproduce la generación y el filtrado a partir del archivo NCI instalado con RDKit, y verifica su hash antes de escribir. Desde la raíz del repositorio, con el entorno científico de Ankora activo, se puede ejecutar:

```sh
PYTHONPATH=backend/src python resources/examples/real_screening_library_100/build_library.py --output directorio-nuevo
```

El directorio de salida no debe existir. Los resultados registrados corresponden a las versiones y planes indicados en `manifest.json`.

## Cómo usarla en Ankora

En **Ligand**, selecciona **Virtual screening** e importa el SDF. Abre la vista previa de filtros, revisa las moléculas pendientes y aplica la selección que consideres científicamente adecuada. Después, Ankora debe generar sus propios conformadores 3D y preparar los PDBQT antes del docking. La tabla conserva las 100 entradas para observar los descartes y las decisiones pendientes.

Con el plan predeterminado de Ankora se obtuvieron **80 elegibles, 2 excluidas y 18 pendientes de decisión** por estereoquímica no definida. Los descriptores y alertas se calcularon para 82 moléculas; entre ellas, 5 tienen alertas PAINS y 47 alertas Brenk. El plan predeterminado señala esas alertas para revisión, no las excluye automáticamente. Las 18 pendientes no se clasificaron como aprobadas ni como excluidas.

Para demostrar más filtros puede elegirse un perfil personalizado que exige Lipinski (máximo una violación), Veber, Ghose y Muegge, fija QED mínimo en 0.3 y excluye coincidencias PAINS y Brenk, además de duplicados. Con ese plan de ejemplo resultaron **11 elegibles, 71 excluidas y 18 pendientes de decisión**, sin duplicados. Cada regla puede coincidir con otras: los motivos individuales no deben sumarse como si fueran exclusiones independientes. Las alertas PAINS y Brenk pueden tener falsos positivos; el umbral QED y la exclusión de alertas son decisiones ilustrativas, no recomendaciones universales.

Se comprobó independientemente la preparación de las 11 moléculas elegibles en ese perfil: las 11 generaron un conformador y un PDBQT con Meeko 0.7.1 en un entorno temporal, usando RDKit 2025.09.6 y semilla 20261029. No se realizó docking con esta biblioteca ni se verificaron actividad biológica, disponibilidad comercial o idoneidad para una diana. Los resultados pueden variar con versiones, configuración y decisiones diferentes.

/**
 * Turning what is on screen into a file a journal will accept (M9).
 *
 * Both halves matter and only one of them is vector:
 *
 * The diagram is an SVG whose colours live in a stylesheet, so serializing the
 * DOM node alone would produce a black-on-transparent skeleton. `inlineSvg`
 * copies the computed value of every property the figure actually uses onto the
 * elements themselves, which is what makes the exported file look like the
 * figure the scientist approved — in Illustrator, in Inkscape, and in a
 * reviewer's browser.
 *
 * The 3D view is a WebGL render. There is no vector inside it, so it is
 * captured as a raster at a stated size and never offered as SVG.
 */

/** Properties a `<line>`, `<circle>`, `<text>` or `<g>` in this figure uses. */
export const CARRIED = [
  "fill",
  "fill-opacity",
  "stroke",
  "stroke-width",
  "stroke-opacity",
  "stroke-dasharray",
  "stroke-linecap",
  "stroke-linejoin",
  // The heteroatom labels are drawn as a halo *under* the coloured letter.
  // Dropped, SVG reverts to painting the 5px halo over the fill and every O,
  // N and Cl disappears into its own outline.
  "paint-order",
  "font-family",
  "font-size",
  "font-weight",
  "text-anchor",
  "dominant-baseline",
  "opacity",
  "visibility",
] as const;

export interface FigureGeometry {
  widthPx: number;
  heightPx: number;
}

/**
 * The figure's pixel size from the measurements a journal actually specifies.
 *
 * A "2×" button means nothing to a submission checklist; a column width in
 * millimetres and a resolution in DPI is exactly what one asks for.
 */
export function figureGeometry(
  aspectRatio: number,
  widthMillimetres: number,
  dpi: number,
): FigureGeometry {
  const widthPx = Math.min(Math.round((widthMillimetres / 25.4) * dpi), 8000);
  const heightPx = Math.max(Math.round(widthPx / (aspectRatio || 1)), 1);
  return { widthPx, heightPx };
}

/**
 * A standalone SVG document with every computed style written onto the nodes.
 *
 * The background is painted explicitly: a transparent figure dropped onto a
 * white page is fine, but the same figure dropped onto a dark slide silently
 * loses every dark-coloured label, and the exporter should not decide that.
 */
export function inlineSvg(
  source: SVGSVGElement,
  { background }: { background: string | null },
): string {
  const clone = source.cloneNode(true) as SVGSVGElement;
  const originals = [source, ...Array.from(source.querySelectorAll("*"))];
  const clones = [clone, ...Array.from(clone.querySelectorAll("*"))];

  originals.forEach((element, index) => {
    const target = clones[index];
    if (!(target instanceof SVGElement) && !(target instanceof HTMLElement)) return;
    const computed = window.getComputedStyle(element);
    const declarations = CARRIED
      .map((property) => [property, computed.getPropertyValue(property)] as const)
      .filter(([, value]) => value && value !== "auto")
      .map(([property, value]) => `${property}:${portableColor(value)}`);
    if (declarations.length) target.setAttribute("style", declarations.join(";"));
    // Interaction hooks are noise in a file nobody can click.
    target.removeAttribute("class");
    target.removeAttribute("tabindex");
    target.removeAttribute("role");
  });

  const box = source.viewBox.baseVal;
  const width = box.width || source.clientWidth;
  const height = box.height || source.clientHeight;
  clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  clone.setAttribute("width", `${width}`);
  clone.setAttribute("height", `${height}`);
  clone.setAttribute("viewBox", `${box.x} ${box.y} ${width} ${height}`);
  if (background) {
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("x", `${box.x}`);
    rect.setAttribute("y", `${box.y}`);
    rect.setAttribute("width", `${width}`);
    rect.setAttribute("height", `${height}`);
    rect.setAttribute("fill", background);
    clone.insertBefore(rect, clone.firstChild);
  }
  return new XMLSerializer().serializeToString(clone);
}

/** The same SVG, rasterized at an exact pixel size. Returns a PNG data URI. */
export async function rasterizeSvg(
  svg: string,
  { widthPx, heightPx }: FigureGeometry,
): Promise<string> {
  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const image = await loadImage(url);
    const canvas = document.createElement("canvas");
    canvas.width = widthPx;
    canvas.height = heightPx;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("This browser could not rasterize the figure.");
    context.drawImage(image, 0, 0, widthPx, heightPx);
    return canvas.toDataURL("image/png");
  } finally {
    URL.revokeObjectURL(url);
  }
}

/**
 * A colour every SVG renderer understands.
 *
 * Chrome resolves this app's `color-mix()` values into CSS Color 4 syntax
 * (`color(srgb 1 1 1)`), which Inkscape, Illustrator and most journal
 * pipelines do not read - the paint silently becomes black or nothing. The
 * figure has to survive leaving the browser it was drawn in.
 */
export function portableColor(value: string): string {
  return value.replace(
    /color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\s*\)/g,
    (_, r: string, g: string, b: string, alpha: string | undefined) => {
      const channel = (raw: string) =>
        Math.max(0, Math.min(255, Math.round(Number(raw) * 255)));
      const rgb = `${channel(r)}, ${channel(g)}, ${channel(b)}`;
      return alpha === undefined || Number(alpha) === 1
        ? `rgb(${rgb})`
        : `rgba(${rgb}, ${Number(alpha)})`;
    },
  );
}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("The figure could not be rendered for export."));
    image.src = url;
  });
}

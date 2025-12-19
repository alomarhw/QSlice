from __future__ import annotations
import argparse
from pathlib import Path

from qpdg_builder import load_outjson, QPDGBuilder
from qpdg_viz import write_dot, render_with_graphviz


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outjson", required=True, help="Path to QStatic out.json")
    ap.add_argument("--dot", default="qpdg.dot", help="Output DOT file")
    ap.add_argument("--render", action="store_true", help="Render DOT via graphviz 'dot'")
    ap.add_argument("--png", default="qpdg.png", help="PNG output path (if --render)")
    ap.add_argument("--no-edge-labels", action="store_true")
    args = ap.parse_args()

    out = load_outjson(args.outjson)
    builder = QPDGBuilder()
    g = builder.build_from_outjson(out)

    dot_path = write_dot(g, args.dot, show_edge_labels=not args.no_edge_labels)
    print(f"Wrote DOT: {dot_path} (nodes={len(g.nodes)} edges={len(g.edges)})")

    if args.render:
        render_with_graphviz(dot_path, args.png, fmt="png")
        print(f"Rendered PNG: {args.png}")


if __name__ == "__main__":
    main()


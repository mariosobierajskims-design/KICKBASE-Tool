"""Zerlegt artifact_data/players.json in Einzeldateien pro Spieler plus
Batch-Manifeste (je <=50 Eintraege) fuer den Artifact-Tool-Aufruf
`write_db` (db_op "batch", jeder Eintrag per file_path). Getrennt von
export_artifact.py, damit sich beide Schritte unabhaengig wiederholen lassen.

Nutzung: python -m kickbase_tool.prepare_batches [--in artifact_data/players.json] [--chunk-size 50]
"""
import argparse
import json
import math
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Batch-Manifeste fuer den Artifact-DB-Import vorbereiten")
    parser.add_argument("--in", dest="input", type=str, default="artifact_data/players.json")
    parser.add_argument("--chunk-size", type=int, default=50)
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    base_dir = in_path.parent
    docs_dir = base_dir / "player_docs"
    manifests_dir = base_dir / "batch_manifests"
    docs_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    rows = json.loads(in_path.read_text(encoding="utf-8"))

    for r in rows:
        doc_path = docs_dir / f"{r['id']}.json"
        doc_path.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")

    n = math.ceil(len(rows) / args.chunk_size)
    for i in range(n):
        chunk = rows[i * args.chunk_size:(i + 1) * args.chunk_size]
        writes = [
            {"op": "set", "collection": "players", "doc_id": r["id"], "file_path": str(docs_dir / f"{r['id']}.json")}
            for r in chunk
        ]
        manifest_path = manifests_dir / f"manifest_{i:02d}.json"
        manifest_path.write_text(json.dumps(writes), encoding="utf-8")

    print(f"{len(rows)} Spieler-Dokumente unter {docs_dir}/ geschrieben")
    print(f"{n} Batch-Manifeste unter {manifests_dir}/ geschrieben (je bis zu {args.chunk_size} Eintraege)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

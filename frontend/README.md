# React dashboard source

The shipping dashboard is React-based and prebuilt under `src/contextbridge/dashboard_static`, so
running ContextBridge does **not** require Node/npm. The repository keeps the TSX source here for
review and future UI work.

The packaged runtime currently vendors the MIT-licensed React 16 production UMD bundles to make the
control plane fully offline and self-contained. See `THIRD_PARTY_NOTICES.md`.

def query_graph(graph, query):
    q = query.lower().split()
    scores = {}
    neighbor_map = {}
    for e in graph["edges"]:
        neighbor_map.setdefault(e["source"], set()).add(e["target"])
        neighbor_map.setdefault(e["target"], set()).add(e["source"])
    for n in graph["nodes"]:
        score = 0
        for kw in q:
            if kw in n["label"].lower():
                score += 3
            if any(kw in t.lower() for t in n.get("tags", [])):
                score += 2
        for nb in neighbor_map.get(n["id"], set()):
            nb_node = next((x for x in graph["nodes"] if x["id"] == nb), None)
            if nb_node:
                for kw in q:
                    if kw in nb_node["label"].lower():
                        score += 1
        if score > 0:
            scores[n["id"]] = score
    top = sorted(scores, key=lambda x: -scores[x])[:5]
    return [
        {**next(n for n in graph["nodes"] if n["id"] == rid), "score": scores[rid]}
        for rid in top
    ]

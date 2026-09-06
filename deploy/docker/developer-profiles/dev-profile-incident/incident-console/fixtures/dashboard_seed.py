"""Synthetic review fixtures only. Never imported by the database layer.

Timestamps are video-relative HH:MM:SS; Duration is seconds; confidence is 0–1.
All URLs are opaque, deliberately non-resolving placeholders. IDs are local to
an incident for entities/instruments/assets; joins include Incident_ID.
"""


def load_seed():
    templates = [
        ("animal", "monkey knocks over vase of flowers", 2, 4, 8, None, "monkey beside table"),
        ("animal", "leopard enters the home and attacks man", 2, 12, 18, None, "leopard near doorway"),
        ("animal", "snake attacks man, man runs", 2, 6, 7, None, "snake on floor"),
        ("animal", "bear enters convenience store", 1, 20, 40, 0.88, "bear beside shelves"),
        ("animal", "squirrel jumps onto man inside", 3, 32, 3, None, "squirrel on chair"),
        ("animal", "boy is sitting down and playing", 1, 0, 15, None, None),
        ("animal", "monitor lizard knocks over trash can", 2, 45, 12, None, "monitor lizard beside trash can"),
        ("animal", "monkey pulls blue bag from man's hand", 2, 65, 9, 0.61, "monkey holding bag"),
        ("animal", "bear sniffs box outside shop and walks away", 1, 80, 25, None, "bear outside shop"),
        ("animal", "snake moves towards woman, woman steps back", 2, 96, 6, None, "snake near steps"),
        ("animal", "monkey jumps onto table, boy moves away", 2, 120, 10, 0.74, "monkey on table"),
        ("animal", "dog runs towards man carrying box", 2, 150, 14, None, "dog near entrance"),
        ("fighting", "two men exchange punches outside shop", 4, 10, 18, 0.56, None),
        ("fighting", "man raises firearm, people run from entrance", 5, 42, 8, None, None),
        ("explosion", "brief flash and smoke near parked vehicle", 5, 72, 5, 0.48, None),
        ("explosion", "small blast scatters debris beside doorway", 4, 100, 4, 0.82, None),
        ("road accident", "car strikes roadside barrier and stops", 3, 132, 11, 0.93, None),
        ("burglary", "man forces shop door and carries box out", 3, 165, 28, 0.67, None),
    ]
    data = {name: [] for name in ("Incident", "Entity", "Instrument", "Asset", "Report", "Video", "Query")}

    def timestamp(seconds):
        return f"00:{seconds // 60:02d}:{seconds % 60:02d}"

    for n, (kind, description, severity, start, duration, confidence, animal) in enumerate(templates, 1):
        incident_id = f"MOCK-{n:03d}"
        filename = f"seed_clip_{n:02d}.mp4"
        base = {"Filename": filename, "Incident_ID": incident_id}
        url = f"https://media.example.invalid/seed/{n}"
        row = dict(
            base,
            Type=kind,
            Start_Timestamp=timestamp(start),
            End_Timestamp=timestamp(start + duration),
            Duration=duration,
            Description=description,
            Severity=severity,
            Source=f"{url}/source",
        )
        if confidence is not None:
            row["Confidence_Score"] = confidence
        data["Incident"].append(row)
        humans = [
            "man wearing white shirt",
            "young boy wearing white shirt and slippers",
            "woman wearing black shirt and hijab and carrying baby",
        ]
        descriptions = [("human", humans[(n - 1) % 3])]
        if animal:
            descriptions.append(("animal", animal))
        if n in (1, 10, 13):
            descriptions.append(("human", "man wearing dark trousers"))
        if n == 15:
            descriptions.append(("unknown", "partially obscured figure behind smoke"))
        for e, (entity_type, desc) in enumerate(descriptions, 1):
            data["Entity"].append(
                dict(base, ID=f"E{e}", Type=entity_type, Description=desc, Image=f"{url}/entity-{e}.jpg")
            )
        instruments = {
            8: ("bag", "blue bag with pizza inside", 1),
            9: ("box", "cardboard box beside shop", 1),
            12: ("box", "box carried by man", 1),
            14: ("firearm", "firearm held by man near entrance", 5),
        }
        if n in instruments:
            name, desc, threat = instruments[n]
            data["Instrument"].append(
                dict(
                    base,
                    Entity_ID="E1",
                    ID="I1",
                    Name=name,
                    Description=desc,
                    Threat_Level=threat,
                    Image=f"{url}/instrument-1.jpg",
                )
            )
        assets = {
            1: ("flower vase", "flower vase knocked down from table by monkey"),
            7: ("trash can", "trash can knocked over by monitor lizard"),
        }
        if n in assets:
            name, desc = assets[n]
            data["Asset"].append(dict(base, ID="A1", Name=name, Description=desc, Image=f"{url}/asset-1.jpg"))
        data["Video"].append(
            {
                "ID": f"V{n}",
                "Filepath": f"{url}/{filename}",
                "Uploaded_DateTime": "2026-09-01T09:00:00Z",
                "Duration": start + duration + 5,
                "Source": f"{url}/source",
            }
        )
    return data

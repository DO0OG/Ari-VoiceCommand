from __future__ import annotations

import io
import json
import os
import zipfile

import requests
from supabase import create_client


def main() -> None:
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    plugin = (
        supabase.table("plugins")
        .select("*")
        .eq("id", os.environ["PLUGIN_ID"])
        .single()
        .execute()
        .data
    )
    signed = supabase.storage.from_("plugin-uploads").create_signed_url(plugin["zip_url"], 300)
    response = requests.get(signed["signedURL"], timeout=30)
    response.raise_for_status()

    os.makedirs("./plugin", exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extractall("./plugin")

    with open("plugin_meta.json", "w", encoding="utf-8") as handle:
        json.dump(plugin, handle, ensure_ascii=False, indent=2)

    print(f"downloaded {plugin['name']} v{plugin['version']}")


if __name__ == "__main__":
    main()

import asyncio
import io
import time
import httpx

BASE_URL = "http://localhost:8000"


async def main() -> None:
    print("=" * 60)
    print("DROP EXPIRATION DEMONSTRATION TEST")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15.0) as client:
        print("\n1. Creating drop with 5-second expiration TTL...")
        files = {"file": ("expire_demo.txt", io.BytesIO(b"Expiration test content"), "text/plain")}
        data = {"expires_in_seconds": "5", "max_downloads": "10"}

        resp = await client.post("/api/v1/drops", files=files, data=data)
        if resp.status_code != 201:
            print(f"Error creating drop: {resp.status_code} {resp.text}")
            return

        public_id = resp.json()["public_id"]
        print(f"   Created drop: {public_id} (TTL = 5 seconds)")

        print("\n2. Immediate download before expiration...")
        before_resp = await client.get(f"/api/v1/drops/{public_id}/download")
        print(f"   Before expiration status: {before_resp.status_code} (Expected: 200)")

        print("\n3. Sleeping for 6 seconds to trigger expiration...")
        await asyncio.sleep(6)

        print("\n4. Download after expiration...")
        after_resp = await client.get(f"/api/v1/drops/{public_id}/download")
        print(f"   After expiration status: {after_resp.status_code} (Expected: 410 Gone)")

        if after_resp.status_code == 410:
            print("\n   SUCCESS: Expired drop correctly rejected by API!")
        else:
            print(f"\n   FAILURE: Expected HTTP 410, got {after_resp.status_code}")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

import asyncio
import io
import time
import httpx

BASE_URL = "http://localhost:8000"


async def main() -> None:
    print("=" * 60)
    print("DROP CONCURRENCY TEST (RACE TEST)")
    print("=" * 60)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        # 1. Create single-use drop (max_downloads=1)
        print("\n1. Creating 1-download drop...")
        files = {"file": ("test_race.txt", io.BytesIO(b"Race condition payload"), "text/plain")}
        data = {"expires_in_seconds": "3600", "max_downloads": "1"}

        resp = await client.post("/api/v1/drops", files=files, data=data)
        if resp.status_code != 201:
            print(f"Error creating drop: {resp.status_code} {resp.text}")
            print("Ensure the API server is running (docker compose up -d or uvicorn drop.main:app)")
            return

        drop_data = resp.json()
        public_id = drop_data["public_id"]
        print(f"   Created drop: {public_id} (max_downloads=1)")

        # 2. Execute 100 concurrent download requests
        print("\n2. Executing 100 concurrent download attempts...")
        concurrent_clients = 100
        start_time = time.perf_counter()

        tasks = [
            client.get(f"/api/v1/drops/{public_id}/download")
            for _ in range(concurrent_clients)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - start_time

        success_count = 0
        rejected_count = 0

        for r in results:
            if isinstance(r, httpx.Response):
                if r.status_code == 200:
                    success_count += 1
                elif r.status_code in (410, 409):
                    rejected_count += 1

        print(f"\n3. Results (elapsed {elapsed:.2f}s):")
        print(f"   Concurrent clients: {concurrent_clients}")
        print("   Download limit:     1")
        print(f"   Successful:         {success_count}")
        print(f"   Rejected:           {rejected_count}")

        meta_resp = await client.get(f"/api/v1/drops/{public_id}")
        if meta_resp.status_code == 200:
            final_count = meta_resp.json()["download_count"]
            print(f"   Final counter:      {final_count}")
            invariant_violated = final_count > 1 or success_count > 1
            print(f"   Invariant violated: {'YES (FAIL)' if invariant_violated else 'NO (PASS)'}")
        else:
            print(f"   Drop status check:  {meta_resp.status_code}")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

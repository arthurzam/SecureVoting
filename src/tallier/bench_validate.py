import asyncio
import string
from datetime import datetime, timedelta

from mpc import MpcValidation
from mytypes import Election, ElectionType
from utils import clean_gen_shamir, transpose
from test_mpc import generate_clique_talliers, build_ballot

all_D = [3, 5, 7, 9]
all_M = [3, 5, 10, 15, 20]

p = 2 ** 31 - 1

results = []

async def run(clique_size: int, candidates_count: int, ballots_count: int, runs: int):
    candidates = tuple(string.ascii_uppercase)[:candidates_count]
    mock_election = Election(None, "Arthur", "a@a.com", ElectionType.copeland, candidates, 1, p, 5)

    tallier_size = candidates_count * (candidates_count - 1) // 2
    talliers = generate_clique_talliers(clique_size=clique_size, tallier_size=tallier_size)
    clique = tuple(MpcValidation(mock_election, t) for t in talliers)
    await asyncio.gather(*(t.init_randoms(0) for t in clique))

    ballot = build_ballot(tuple(range(candidates_count)))
    shares = transpose(clean_gen_shamir(x, len(clique), (len(clique) + 1) // 2, p) for x in ballot)

    async def code(t: MpcValidation, x: tuple[int, ...]):
        await t.validate_copeland(0, x)

    times = []
    for _ in range(runs):
        start = datetime.now()
        await asyncio.gather(*map(code, clique, shares))
        times.append(datetime.now() - start)
    results.append((str(len(clique)), str(candidates_count), str(sum(times, start=timedelta(0)) / len(times))))

    await asyncio.gather(*(t.close() for t in clique))

async def main():
    for D in all_D:
        for M in all_M:
            await run(D, M, 1, 100)

    import csv
    with open("/tmp/bench_validate.csv", "w") as f:
        writer = csv.writer(f)
        writer.writerow(["D", "M", "time"])
        writer.writerows(results)

if __name__ == '__main__':
    asyncio.set_event_loop(loop := asyncio.new_event_loop())
    loop.run_until_complete(main())

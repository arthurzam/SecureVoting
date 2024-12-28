import asyncio
import string
from datetime import datetime, timedelta
from uuid import uuid4

from mpc import MpcValidation, MpcWinner
from mytypes import Election, ElectionType
from utils import clean_gen_shamir, transpose
from test_mpc import generate_clique_talliers, build_ballot

all_D = [3, 5, 7, 9]
all_M = [3, 5, 10, 15, 20]

p = 2 ** 31 - 1

results = []

async def run(clique_size: int, candidates_count: int, runs: int):
    candidates = tuple(string.ascii_uppercase)[:candidates_count]
    mock_election = Election(uuid4(), "Arthur", "a@a.com", ElectionType.maximin, candidates, 1, p, 5)

    talliers = generate_clique_talliers(clique_size=clique_size, tallier_size=1)
    clique = tuple(MpcWinner(mock_election, t) for t in talliers)
    await asyncio.gather(*(t.init_randoms(0) for t in clique))

    ballot = build_ballot(tuple(range(candidates_count)), is_maximin=True)
    shares = transpose(clean_gen_shamir(x, len(clique), (len(clique) + 1) // 2, p) for x in ballot)

    async def code(t: MpcWinner, votes_vector: tuple[int, ...]):
        votes_vector = await t.maximin_scores(0, candidates_count, votes_vector)
        await t.max(0, votes_vector)

    times = []
    for _ in range(runs):
        start = datetime.now()
        await asyncio.gather(*map(code, clique, shares))
        times.append(datetime.now() - start)
    results.append((str(len(clique)), str(candidates_count), str(sum(times, start=timedelta(0)) / len(times))))
    print(str(len(clique)), str(candidates_count), str(sum(times, start=timedelta(0)) / len(times)))

    await asyncio.gather(*(t.close() for t in clique))

async def main():
    for D in all_D:
        for M in all_M:
            await run(D, M, 100)

    import csv
    with open("/tmp/bench_winners_miximin.csv", "w") as f:
        writer = csv.writer(f)
        writer.writerow(["D", "M", "time"])
        writer.writerows(results)

if __name__ == '__main__':
    asyncio.set_event_loop(loop := asyncio.new_event_loop())
    loop.run_until_complete(main())

"""Read-only regional lookup probe. Run as python -m scripts.probe_aion2 --help."""
import argparse
import asyncio
import json
import aiohttp
from src.dashboard.aion import AionAdapter, AionError


async def probe(args):
    async with aiohttp.ClientSession(headers={'User-Agent': 'CompanyRoster/1.0'}) as session:
        api = AionAdapter(session)
        servers = await api.servers(args.region)
        results = await api.search(args.region, args.name, args.server, args.race)
        report = {'region': args.region, 'servers': len(servers), 'matches': len(results)}
        exact = [hit for hit in results if hit['name'].casefold() == args.name.casefold()]
        report['exact_matches'] = len(exact)
        if len(exact) == 1:
            hit = exact[0]
            data = await api.character(args.region, hit['server_id'], hit['character_id'])
            # Print capability evidence, not a full player's profile.
            report.update(summary_available=True, character_name=data['name'], server_name=data.get('server_name'),
                          server_id=hit['server_id'], equipment_status=data.get('equipment_status'),
                          fields=[k for k, v in data.items() if v is not None], equipment_items=len(data['equipment']))
        else:
            report['summary_available'] = False
            report['status'] = 'ambiguous_name' if exact else 'exact_name_not_in_first_page'
            report['candidates'] = [{'name': hit['name'], 'server_name': hit.get('server_name'),
                                     'server_id': hit['server_id']} for hit in (exact or results)]
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--region', required=True, choices=['nae','naw','eu','sa','asia','kr','tw'])
    parser.add_argument('--name', required=True)
    parser.add_argument('--server', type=int)
    parser.add_argument('--race', type=int, choices=[1,2], default=1)
    try:
        asyncio.run(probe(parser.parse_args()))
    except AionError as e:
        print(json.dumps({'status': e.kind, 'retry_after': e.retry_after}))
        raise SystemExit(1)

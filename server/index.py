from asyncio import gather
from collections import defaultdict

from sanic import Sanic
from sanic.response import json

from blueprints.cluster import cluster_bp
from blueprints.terminal import terminal_bp
from blueprints.index import index_bp
from blueprints.alias import alias_bp, get_index_aliases
from connections import get_client

app = Sanic()
app.blueprint(index_bp, url_prefix='/api/v1/index')
app.blueprint(terminal_bp, url_prefix='/api/v1/terminal')
app.blueprint(cluster_bp, url_prefix='/api/v1/cluster')
app.blueprint(alias_bp, url_prefix='/api/v1/alias')


def format_index_data(data, aliases):
    append = {}
    if data['index'] in aliases:
        append = {"aliases": aliases[data['index']]}
    if data['status'] == 'close':
        return dict(status=data["status"], **append)
    return dict({
        "primaries": int(data["pri"]),
        "replicas": int(data["rep"]),
        "status": data["status"],
        "docsCount": int(data["docs.count"]),
        "docsDeleted": int(data["docs.deleted"]),
        "storeSize": data["store.size"],
    }, **append)


async def get_cluster_info():
    client = get_client()
    [info], [docs], settings = await gather(client.cat.health(format='json'),
                                            client.cat.count(format='json'),
                                            client.cluster.get_settings(flat_settings=True))
    return {
        "relocatingShards": int(info['relo']),
        "initializingShards": int(info['init']),
        "unassignedShards": int(info['unassign']),
        "numOfPrimaryShards": int(info['pri']),
        "numOfReplicaShards": int(info["shards"]) - int(info['pri']),
        "numberOfNodes": int(info['node.total']),
        "numberOfDocs": int(docs['count']),
        "clusterName": info['cluster'],
        "clusterStatus": info['status'].title(),
        "settings": {
            "allocation": settings['transient'].get('cluster.routing.allocation.enable', 'all')
        },
    }


async def get_nodes_info():
    client = get_client()
    info = await client.nodes.stats(metric='jvm,os,fs')
    result = []
    for node in info['nodes'].values():
        result.append({
            "name": node["name"],
            "isMaster": False,
            "ip": node["ip"],
            "roles": node["roles"],
            "metrics": {
                # Reduce precision in order to reduce render loops in UI
                "CPUPercent": int(node['os']['cpu']['percent']),
                "heapPercent": int(node['jvm']['mem']['heap_used_percent']),
                "load1Percent": int(float(node['os']['cpu']['load_average']['1m']) / 4),  # TODO: Count CPUs

                "diskPercent": int(
                    node['fs']['total']['available_in_bytes'] * 100 / node['fs']['total']['total_in_bytes'])
            }
        })
    return result


@app.route('/api/v1/shards_grid')
async def indices_stats(request):
    client = get_client()
    indices, aliases, shards, nodes, cluster_info = await gather(client.cat.indices(format='json'),
                                                                 get_index_aliases(),
                                                                 client.cat.shards(format='json'),
                                                                 get_nodes_info(),
                                                                 get_cluster_info())
    cluster_info["numOfIndices"] = len(indices)
    relocating_indices = list({shard['index'] for shard in shards if shard['state'] == 'RELOCATING'})
    recovery = await client.cat.recovery(index=relocating_indices, format='json')
    relocation_progress = {
        (recovery_data["index"], recovery_data["shard"]):
            int(float(recovery_data["bytes_recovered"]) * 100 / int(recovery_data["bytes_total"]))
        for recovery_data in recovery if recovery_data["stage"] != "done"
    }

    indices_per_node = defaultdict(lambda: defaultdict(lambda: {'replicas': [], 'primaries': []}))
    unassigned_shards = defaultdict(lambda: {'replicas': [], 'primaries': []})
    for shard in shards:
        if shard['prirep'] == 'p':
            shard_type = 'primaries'
        elif shard['prirep'] == 'r':
            shard_type = 'replicas'
        else:
            raise RuntimeError('Unknown shard type %s' % shard['prirep'])
        data = {
            "shard": int(shard['shard']),
            "state": shard['state'],
        }
        node = shard['node']
        if shard['state'] == 'UNASSIGNED':
            unassigned_shards[shard['index']][shard_type].append(data)
        if shard['state'] == 'RELOCATING':
            node = node.split(' ->')[0]
            data['progress'] = relocation_progress[(shard['index'], shard['shard'])]
        if shard['state'] == 'INITIALIZING':
            data['progress'] = relocation_progress[(shard['index'], shard['shard'])]
        indices_per_node[node][shard['index']][shard_type].append(data)
        indices_per_node[node][shard['index']][shard_type].sort(key=lambda x: x['shard'])

    for node in nodes:
        node['indices'] = dict(sorted(indices_per_node[node["name"]].items()))

    indices = dict([(x['index'], format_index_data(x, aliases)) for x in indices])
    for index in indices:
        if index in unassigned_shards:
            indices[index]['unassignedShards'] = unassigned_shards[index]

    return json({
        "nodes": sorted(nodes, key=lambda x: x["name"]),
        "indices": indices,
        "cluster": cluster_info,
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)

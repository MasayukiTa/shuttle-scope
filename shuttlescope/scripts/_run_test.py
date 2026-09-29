"""Test dataset creation targeting port 8766"""
import urllib.request, urllib.error, json, sys

BASE = "http://localhost:8766/api"

def req(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(BASE+path, data=data, headers={"Content-Type":"application/json"}, method=method)
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[ERROR] {method} {path}: {e.read().decode()}")
        sys.exit(1)

pa = req("POST", "/players", {"name":"田中 太郎","name_en":"Taro Tanaka","team":"東大BC","dominant_hand":"R","birth_year":2000,"is_target":True})
pb = req("POST", "/players", {"name":"山田 次郎","name_en":"Jiro Yamada","team":"京大BC","dominant_hand":"R","birth_year":2001,"is_target":False})
print(f"Players: A={pa['data']['id']}, B={pb['data']['id']}")

m = req("POST", "/matches", {
    "tournament":"テスト大会2024","tournament_level":"国内","round":"QF",
    "date":"2024-10-01","format":"singles",
    "player_a_id":pa["data"]["id"],"player_b_id":pb["data"]["id"],
    "result":"win","annotation_status":"in_progress","annotation_progress":0.0
})
mid = m["data"]["id"]
print(f"Match: {mid}")

s = req("POST", "/sets", {"match_id":mid,"set_num":1})
sid = s["data"]["id"]
print(f"Set1: {sid}")

RALLIES = [
    ("player_a","ace",[("player_a","short_service",None,"NL",False,False),("player_b","net_shot","NL","NC",False,False),("player_a","push_rush","NC","NR",False,False)]),
    ("player_b","forced_error",[("player_a","short_service",None,"NC",False,False),("player_b","clear","NC","BC",False,False),("player_a","smash","BC","ML",False,False),("player_b","defensive","ML","BC",False,False),("player_a","smash","BC","MR",False,False),("player_b","cant_reach",None,None,False,False)]),
    ("player_a","net",[("player_a","long_service",None,"BC",False,False),("player_b","clear","BC","BC",False,False),("player_a","drop","BC","NL",False,False),("player_b","net_shot","NL","NC",False,False),("player_a","push_rush","NC","NC",False,False)]),
    ("player_a","unforced_error",[("player_a","short_service",None,"NR",False,False),("player_b","net_shot","NR","NL",False,False),("player_a","cross_net","NL","NR",False,False)]),
    ("player_b","out",[("player_a","short_service",None,"NC",False,False),("player_b","lob","NC","BL",True,False),("player_a","clear","BL","BR",False,False),("player_b","smash","BR","ML",False,False),("player_a","lob","ML","BC",False,False),("player_b","smash","BC","MC",False,False)]),
    ("player_a","ace",[("player_a","long_service",None,"BL",False,False),("player_b","clear","BL","BR",True,False),("player_a","around_head","BR","NL",False,True),("player_b","cant_reach",None,None,False,False)]),
    ("player_b","forced_error",[("player_a","short_service",None,"NC",False,False),("player_b","push_rush","NC","NL",False,False),("player_a","cross_net","NL","NR",False,False),("player_b","drive","NR","MC",False,False),("player_a","drive","MC","ML",False,False),("player_b","smash","ML","MR",False,False)]),
    ("player_a","net",[("player_a","short_service",None,"NL",False,False),("player_b","flick","NL","BC",False,False),("player_a","smash","BC","ML",False,False),("player_b","block","ML","NC",False,False),("player_a","push_rush","NC","NR",False,False)]),
    ("player_a","unforced_error",[("player_a","long_service",None,"BC",False,False),("player_b","drop","BC","NR",False,False),("player_a","net_shot","NR","NC",False,False),("player_b","cross_net","NC","NL",False,False),("player_a","push_rush","NL","NL",False,False)]),
    ("player_b","forced_error",[("player_a","short_service",None,"NC",False,False),("player_b","lob","NC","BC",True,False),("player_a","half_smash","BC","MR",False,False),("player_b","defensive","MR","BL",False,False),("player_a","smash","BL","ML",False,False),("player_b","lob","ML","BL",False,False),("player_a","smash","BL","MR",False,False),("player_b","cant_reach",None,None,False,False)]),
]

sa,sb = 0,0
for rn,(winner,end_type,strokes) in enumerate(RALLIES,1):
    nsa = sa+(1 if winner=="player_a" else 0)
    nsb = sb+(1 if winner=="player_b" else 0)
    sl = [{"stroke_num":i+1,"player":p,"shot_type":st,"hit_zone":hz,"land_zone":lz,"is_backhand":bh,"is_around_head":ah,"above_net":None,"is_cross":False,"timestamp_sec":float(rn*30+i*3)} for i,(p,st,hz,lz,bh,ah) in enumerate(strokes)]
    req("POST","/strokes/batch",{"rally":{"set_id":sid,"rally_num":rn,"server":"player_a","winner":winner,"end_type":end_type,"rally_length":len(strokes),"score_a_after":nsa,"score_b_after":nsb,"is_deuce":False,"video_timestamp_start":float(rn*30)},"strokes":sl})
    sa,sb = nsa,nsb
    print(f"  Rally {rn:2d}: {winner} ({end_type}) {len(strokes)}球 -> {sa}-{sb}")

req("PUT",f"/sets/{sid}/end",{"winner":"player_a" if sa>sb else "player_b","score_a":sa,"score_b":sb})
print(f"Set1 done: {sa}-{sb}")
print(f"Match ID: {mid} (use this in the annotator)")

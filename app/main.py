#!/usr/bin/env python3

import os
from flask import Flask, request
from neo4j import GraphDatabase
from flask_cors import CORS
from json import dumps

app = Flask(__name__)
CORS(app)

uri = os.environ['DATABASE_URI']
auth = (os.environ['USER'], os.environ['PASSWORD'])
driver = GraphDatabase.driver(uri, auth=auth)

@app.route('/api/family/members', methods=['GET'])
def get_family_memebers():
	with driver.session() as session:
		people_query_res = session.run('MATCH (p:Person) RETURN p.id AS id, p.name AS name, p.surname as surname')
		people = people_query_res.data()
		return dumps(people)

@app.route('/api/spouses', methods=['GET'])
def get_spouses():
	with driver.session() as session:
		spouse_relations_query_res = session.run('MATCH (p1:Person)-[r: SPOUSE]->(p2:Person) RETURN p1, p2')
		spouse_relations = [[result['p1'], result['p2']] for result in spouse_relations_query_res.data()]
		return dumps(spouse_relations)

@app.route('/api/familytree', methods=['GET'])
def get_family_tree():
	with driver.session() as session:
		def get_tree_for_person(person):
			result = {}
			result['name'] = person['name'] + ' ' + person['surname']
			result['extra'] = {'id': person['id']}

			spouses_query_res = session.run(f"MATCH (a:Person {{id: {person['id']}}})-[r:SPOUSE]-(b:Person) RETURN b as spouse")
			spouses = [result['spouse'] for result in spouses_query_res.data()]
			marriages = []
			for spouse in spouses:
				marriage = {}
				marriage['spouse'] = {'name': spouse['name'] + ' ' + spouse['surname'], 'extra': {'id': spouse['id']}}
				children_query_res = session.run(f'''
								MATCH (parent1 {{id: {person['id']}}})-[:CHILD]->(child),
								(parent2 {{id: {spouse['id']}}})-[:CHILD]->(child)
								RETURN child''')
				children = [result['child'] for result in children_query_res.data()]
				marriage['children'] = [get_tree_for_person(child) for child in children]
				marriages.append(marriage)
			result['marriages'] = marriages
			return result

		root = session.run('''
					MATCH (n: Person)
                                        WHERE (n)-[:CHILD]->() AND NOT ()-[:CHILD]->(n)
                                        MATCH p = (n)-[:CHILD*0..]->(m)
                                        WITH n, length(p) AS L
                                        RETURN n as root
                                        ORDER BY L DESC
                                        LIMIT 1''').data()[0]['root']
		response = get_tree_for_person(root)
		return dumps(response)

@app.route('/api/family/relation', methods=['GET'])
def get_relationship():
	id1 = request.args.get('id1')
	id2 = request.args.get('id2')

	with driver.session() as session:
		relation_path_query_res = session.run(f'''
					MATCH (a:Person {{id: {id1}}}), (b:Person {{id: {id2}}}),
                                        path = shortestPath((a)-[*]-(b))
                                        WHERE length(path) >= 1
                                        RETURN path limit 1;
					''')
		relation_path = relation_path_query_res.single().value()

		get_node_properties = lambda node: {k:v for (k, v) in node.items()}

		relation_path_arr = []
		for node, relationship in zip(relation_path.nodes, relation_path.relationships):
			relation_path_arr.append(get_node_properties(node))
			if relationship.type == 'CHILD':
				if relationship.start_node == node:
					relation_path_arr.append('CHILD')
				else:
					relation_path_arr.append('PARENT')
			else:
				relation_path_arr.append('SPOUSE')
		relation_path_arr.append(get_node_properties(relation_path.nodes[-1]))

		siblings_parents_indexes = {index for index in range(2, len(relation_path_arr) - 2) if relation_path_arr[index - 1] == 'PARENT' and relation_path_arr[index + 1] == 'CHILD'}

		response = [relation_path_arr[0]]
		for index in range(2, len(relation_path_arr), 2):
			if index in siblings_parents_indexes:
				response.append('SIBLING')
			elif index - 2 in siblings_parents_indexes:
				response.append(relation_path_arr[index])
			else:
				response.append(relation_path_arr[index - 1])
				response.append(relation_path_arr[index])

		return dumps(response)

@app.route('/api/add/family/member', methods=['POST'])
def add_family_member():
	new_member = request.get_json()

	with driver.session() as session:
		id = session.run('MATCH (p:Person) RETURN max(p.id) + 1').value()[0]
		if id is None:
			id = 0

		session.run(f"CREATE (n:Person {{id: {id}, name: '{(new_member['name'])}', surname: '{new_member['surname']}'}})")
		return str(id)

@app.route('/api/add/family/relation', methods=['POST'])
def add_family_relation():
	new_relation = request.get_json()

	with driver.session() as session:
		session.run(f'''
			MATCH (a:Person), (b:Person)
			WHERE a.id = {new_relation['from']} AND b.id = {new_relation['to']}
			CREATE (a)-[r:{new_relation['type'].upper()}]->(b)
			''')
		return 'ok'

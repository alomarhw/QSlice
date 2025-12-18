import xml.etree.ElementTree as ET
import json
import sys

#fname = "examples/3.0/adder"
#fname = "examples/custom/hadamard_cnot"

#tree = ET.parse(f'{fname}.qasm.xml')
#print(sys.argv[1].replace("\\","/"))
tree = ET.parse(sys.argv[1].replace("\\","/"))
# tree = ET.parse('examples/3.0/teleport.qasm.xml')
root = tree.getroot()

ns = "{http://www.srcML.org/srcML/src}"
unitary_gates = ["U","p","phase","x","y","z","h","s","sdg","t","tdg","sx","rx","ry","rz","id","u1","u2","u3"]
nary_gates = ["swap"]
unitary_control = ["cx","CX","cy","cz","cp","cphase","crx","cry","crz","ch","cu"]
nary_control = ["ccx","cswap"]
gates = unitary_gates + nary_gates + unitary_control + nary_control

class InvalidQubitArgumentError(Exception):
    """Raised when a qubit argument has yet to be declared"""
    def __init__(self, qubit_name):
        super().__init__(f"Qubit '{qubit_name}' has not been declared at this point")
class ArraySizeMismatchError(Exception):
    """Raised when two or more arrays have mismatching sizes"""
    def __init__(self, array_name_1, array_name_2):
        super().__init__(f"Arrays '{array_name_1}' and '{array_name_2}' do not match in size")

class Counter:
    def __init__(self):
        self.count = 0
    def t(self):
        self.count += 1
        return self.count - 1

# XML elements of functions or gates
scripts = {}

# Stack of maps used to map parameter names to argument names in gates and functions
maps = [{}]

# Globals used in QASM code occasionally
globals = {"pi":3.14159,"π":3.14159}
def replace_globals(string):
    #print("IN",string)
    for operator in ['+','-','*','/','%']:
        string = string.replace(operator,' '+operator+' ')
    tokens = string.split(' ')
    rtn = ""
    for token in tokens:
        if token in globals:
            rtn += str(globals[token])
        else:
            rtn += token
        rtn += ' '
    #print("OUT",rtn)
    return rtn.strip()

# Stack of if conditions to add onto actions
ifs = []
def get_ifs(i):
    if len(i) > 0:
        return {"if":",".join(i)}
    else:
        return {}

# Map of qubit names to information on the qubit
#   {
#       "type" : The type of qubit this is - can be physical ($1), named (a), array (cin[3])
#       "index" : The integer index of an array qubit, appears only if the qubit is an array
#       "map" : The name key of the qubit that this qubit currently maps to
#       "actions" : A list of gate actions performed on each bit. Each action is a map, which looks like:
#           {
#               "action" : The type of action being performed. 
#           }
#   }
qubits = {}

def get_all_ctrls_from_time(time):
    time_data = {}
    for qubit in qubits:
        for action in reversed(qubits[qubit]["actions"]):
            if action["time"] not in time_data:
                time_data[action["time"]] = []
            time_data[action["time"]].append(action | {"qubit":qubit})
    rtn = []
    while time >= 0:
        if time in time_data:
            for action in reversed(time_data[time]):
                if action["action"] != 'ctrl':
                    time = -1
                    break
                rtn.append(action["qubit"])
        time -= 1

    return ",".join(reversed(rtn))



for i in range(6):
    qubits[f"${i}"] = {"type":"physical","actions":[]}


data_queue = []
for child in root[0]:
    data_queue.append(child)

count = Counter()
t = count.t
while len(data_queue) > 0:
    child = data_queue.pop(0)
    if(type(child) == str):
        if child == "pop-map-stack":
            maps.pop(0)
        if child.startswith("add-if-cond"):
            ifs.insert(0," ".join(child.split()[1:]))
        elif child.startswith("pop-if-cond"):
            ifs.pop(0)
        continue
    tag = child.tag.replace(ns,"")

    # Save Script Blocks
    if tag == "gate" or tag == "function":
        name = child.find(f"./{ns}name")
        scripts[name.text] = child

    # New Qubit found, store
    elif tag == "decl_stmt":
        if child.find(f"./{ns}decl/{ns}specifier[.='let']") != None:
            name = "".join(child.find(f"./{ns}decl/{ns}name").itertext())
            target = "".join(child.find(f"./{ns}decl/{ns}init/{ns}expr").itertext())
            target_name = target.split("[")[0]
            start,stop = 0,1
            if "[" in target:
                if ':' in target:
                    start = int(replace_globals(target.split('[')[1].split(':')[0]))
                    end = int(replace_globals(target.split(']')[0].split(':')[1]))+1
                else:
                    start = int(replace_globals(target.split('[')[1].split(']')[0]))
                    end = start+1
            i = start
            while i != end:
                maps[0][name+f"[{i-start}]"] = target_name+f'[{i}]'
                i += 1

        else:
            typ = child.find(f"./{ns}decl/{ns}type/{ns}name")
            typ = "".join(typ.itertext())
            if "qubit" in typ:
                name = child.find(f"./{ns}decl/{ns}name").text
                if "[" in typ:
                    amt = int(replace_globals(typ.split("[")[1][:-1]))
                    for i in range(amt):
                        qubits[f"{name}[{i}]"] = {"type":"array","index":i,"actions":[]}
                else:
                    qubits[name] = {"type":"named","actions":[]}
            elif "const" in "".join(child.find(f"./{ns}decl/{ns}type").itertext()):
                name = child.find(f"./{ns}decl/{ns}name").text
                value = eval(replace_globals("".join(child.find(f"./{ns}decl/{ns}init/{ns}expr").itertext())))
                globals[name] = value
                print("|",globals)


    # Reset Statement
    elif tag == "reset":
        target = "".join(child.find(f"./{ns}expr").itertext())
        line = int(child.attrib["pos"])
        _t = t()
        for qubit in qubits:
            if qubit.startswith(target):
                qubits[qubit]["actions"].append({"action":"reset","time":_t,"line":line} | get_ifs(ifs))

    # expr_stmt, check for a call! Will only find the first call if there are multiple
    elif tag == "expr_stmt":
        line = int(child.attrib["pos"])
        call = child.find(f".//{ns}call")
        if call == None:
            measure_op = child.find(f".//{ns}operator[.='measure']")
            if measure_op == None:
                continue
            expr = "".join(child.find(f"./{ns}expr").itertext())
            store = expr.split("=")[0].strip()
            qubit = expr.split("measure")[1].strip()
            _t = t()
            if qubit in qubits:
                qubits[qubit]["actions"].append({"action":"measure","store":store,"time":_t,"line":line} | get_ifs(ifs))
            elif qubit+"[0]" in qubits:
                for q in qubits:
                    if q.startswith(qubit):
                        qubits[q]["actions"].append({"action":"measure","store":store,"time":_t,"line":line} | get_ifs(ifs))
            else:
                raise InvalidQubitArgumentError(qubit)
            
            continue
        name = call.find(f"./{ns}name").text
        # Get quantum args
        qargs = call.findall(f"./{ns}argument_list[@type='quantum']/{ns}argument")
        qargs = ["".join(x.itertext()) for x in qargs]
        local_qargs = qargs.copy()
        qargs = [(maps[0][arg] if arg in maps[0] else arg) for arg in qargs]
        if len(qargs) == 0:
            continue
        # Check if call is on a function or gate
        if name not in scripts and name not in gates:
            raise Exception("Cannot find valid call name!")
        # NAME is a gate!
        elif name in gates or (name in scripts and scripts[name].tag.endswith("gate")):
            # Check to ensure qubits exist, and are all single
            arrays = []
            size = -1
            for qarg in qargs:
                if qarg not in qubits:
                    if qarg+"[0]" in qubits:
                        arrays.append(qarg)
                        if size == -1:
                            size = sum([(1 if name.startswith(qarg) else 0) for name in qubits])
                        else:
                            if size != sum([(1 if name.startswith(qarg) else 0) for name in qubits]):
                                raise ArraySizeMismatchError(arrays[0],qarg)
                    else:
                        raise InvalidQubitArgumentError(qarg)
            # Duplicate short-hand array calls
            if len(arrays) != 0:
                instructions = []
                for i in range(size):
                    xml_text = ET.tostring(child,encoding='utf-8')
                    xml_text = xml_text.decode().replace("ns0:","").replace(":ns0","")
                    copy = ET.fromstring(xml_text)
                    for qarg in arrays:
                        change_nodes = copy.findall(f".//{ns}argument_list[@type='quantum']/{ns}argument/{ns}expr[{ns}name='{qarg}']")
                        for node in change_nodes:
                            text = ''.join(node.itertext())
                            text = text.replace(qarg,qarg+f"[{i}]")
                            tail = node.tail
                            node.clear()
                            node.text = str(text)
                            node.tail = tail
                    instructions.append(copy)
                data_queue = instructions + data_queue
                continue
            t_set = False
            modifiers = call.findall(f"./{ns}modifier")
            #ctrls = []
            if len(modifiers) > 0:
                t_set = True
                _t = t()
                for modifier in modifiers:
                    if modifier.find(f"./{ns}expr/{ns}call") != None:
                        mname = modifier.find(f"./{ns}expr/{ns}call/{ns}name").text
                        num = int(replace_globals("".join(modifier.find(f"./{ns}expr/{ns}call//{ns}argument").itertext())))
                    elif modifier.find(f"./{ns}expr/{ns}name") != None:
                        mname = modifier.find(f"./{ns}expr/{ns}name").text
                        num = 1
                    else:
                        raise Exception("Weird mofidier")

                    if mname in ["ctrl","negctrl"]:
                        print(num)
                        for i in range(num):
                            qarg = qargs.pop(0)
                            qubits[qarg]["actions"].append({"action":mname,"time":_t,"line":line} | get_ifs(ifs))
                            #ctrls.append(qarg)

            # First, check if call is to any std gate
            if name in gates:
                _t = t() if not t_set else _t
                # If gate is a simple, unitary one
                if name in unitary_gates:
                    qubits[qargs[0]]["actions"].append({"action":"gate-call","type":name,"ctrl":get_all_ctrls_from_time(_t),"time":_t,"line":line,"local_name":local_qargs[0]} | get_ifs(ifs))
                # If gate is a simple control gate
                elif name in unitary_control:
                    qubits[qargs[0]]["actions"].append({"action":"ctrl","time":_t,"line":line,"local_name":local_qargs[0]})
                    # ctrls.append(qargs[0])
                    qubits[qargs[1]]["actions"].append({"action":"ctrl-gate-call","type":name,"ctrl":get_all_ctrls_from_time(_t),"time":_t,"line":line,"local_name":local_qargs[1]} | get_ifs(ifs))
                # If gate is complex, but no control (just swap right now)
                elif name == "swap":
                    qubits[qargs[0]]["actions"].append({"action":"gate-call","type":"swap","with":qargs[1],"ctrl":get_all_ctrls_from_time(_t),"time":_t,"line":line,"local_name":local_qargs[0]} | get_ifs(ifs))
                    qubits[qargs[1]]["actions"].append({"action":"gate-call","type":"swap","with":qargs[0],"ctrl":get_all_ctrls_from_time(_t),"time":_t,"line":line,"local_name":local_qargs[1]} | get_ifs(ifs))
                # If gate is complex control (needs custom per gate)
                elif name == "ccx":
                    qubits[qargs[0]]["actions"].append({"action":"ctrl","time":_t,"line":line,"local_name":local_qargs[0]})
                    # ctrls.append(qargs[0])
                    qubits[qargs[1]]["actions"].append({"action":"ctrl","time":_t,"line":line,"local_name":local_qargs[1]})
                    # ctrls.append(qargs[1])
                    qubits[qargs[2]]["actions"].append({"action":"ctrl-gate-call","type":"ccx","ctrl":get_all_ctrls_from_time(_t),"time":_t,"line":line,"local_name":local_qargs[2]} | get_ifs(ifs))
                elif name == "cswap":
                    qubits[qargs[0]]["actions"].append({"action":"ctrl","time":_t,"line":line,"local_name":local_qargs[0]})
                    # ctrls.append(qargs[0])
                    qubits[qargs[1]]["actions"].append({"action":"ctrl-gate-call","type":"cswap","ctrl":get_all_ctrls_from_time(_t),"with":qargs[2],"time":_t,"line":line,"local_name":local_qargs[1]} | get_ifs(ifs))
                    qubits[qargs[2]]["actions"].append({"action":"ctrl-gate-call","type":"cswap","ctrl":get_all_ctrls_from_time(_t),"with":qargs[1],"time":_t,"line":line,"local_name":local_qargs[2]} | get_ifs(ifs))

            # If not, handle user-defined gates, but ONLY if qargs exists
            elif len(qargs) > 0:
                if name in scripts:
                    script = scripts[name]
                    qparams = script.findall(f"./{ns}parameter_list[@type='quantum']/{ns}parameter")
                    qparams = ["".join(x.itertext()) for x in qparams]
                    assert len(qargs) == len(qparams)
                    maps.insert(0,maps[0] | {qparams[i]:qargs[i] for i in range(len(qargs))})
                    instructions = []
                    for instr in script.find(f"./{ns}block/{ns}block_content"):
                        instructions.append(instr)
                    instructions.append("pop-map-stack")
                    data_queue = instructions + data_queue
                # Can't find the gate
                else:
                    _t = t() if not t_set else _t
                    for i in len(qargs):
                        qubits[qargs[i]]["actions"].append({"action":"gate-call","type":name,"status":"unknown","ctrl":get_all_ctrls_from_time(_t),"time":_t,"local_name":local_qargs[i]} | get_ifs(ifs))
        
        elif name in scripts and scripts[name].tag.endswith("function"):
            script = scripts[name]
            qparams = script.findall(f"./{ns}parameter_list/{ns}parameter")
            qparams = ["".join(qparam.itertext()) for qparam in qparams if "qubit" in "".join(qparam.itertext())]
            # print("@",name,qparams)
            assert len(qargs) == len(qparams)
            new_map = {}
            for i in range(len(qargs)):
                qarg, qparam = qargs[i], qparams[i]
                if '[' in qparam:
                    size = int(replace_globals(qparam.split('[')[1].split(']')[0]))
                    param_name = qparam.split('[')[0]
                    for j in range(size):
                        new_map |= {param_name+f"[j]":qarg+f"[j]"}
                else:
                    new_map |= {qparam:qarg}
            maps.insert(0,maps[0] | new_map)
            instructions = []
            for instr in script.find(f"./{ns}block/{ns}block_content"):
                instructions.append(instr)
            instructions.append("pop-map-stack")
            data_queue = instructions + data_queue
        else:
            raise Exception("Should not reach here")

    elif tag == "if_stmt":
        instructions = []
        if_stmt = child.find(f"./{ns}if")
        if_cond = "".join(if_stmt.find(f"./{ns}condition/{ns}expr").itertext())
        if_block = if_stmt.find(f"./{ns}block/{ns}block_content")
        instructions.append("add-if-cond "+if_cond)
        for stmt in if_block:
            instructions.append(stmt)
        instructions.append("pop-if-cond")
        data_queue = instructions + data_queue

    elif tag == "for":
        loop_name = child.find(f"./{ns}control/{ns}init/{ns}decl/{ns}name").text
        index = "".join(child.find(f"./{ns}control/{ns}range/{ns}expr/{ns}index/{ns}expr").itertext())
        for_block = child.find(f"./{ns}block/{ns}block_content")
        index = index.split(":")
        start = eval(replace_globals(index[0]))
        stop = eval(replace_globals(index[-1].replace("]","")))
        step = eval(replace_globals(index[1])) if len(index) == 3 else 1
        loop_range = list(range(start, stop+1 if stop > start else stop - 1,step))
        instructions = []
        for val in loop_range:
            xml_text = ET.tostring(for_block,encoding='utf-8')
            xml_text = xml_text.decode().replace("ns0:","").replace(":ns0","")[:-1]
            copy = ET.fromstring(xml_text)
            change_nodes = copy.findall(f".//{ns}expr[{ns}name='{loop_name}']")
            for node in change_nodes:
                text = ''.join(node.itertext())
                text = text.replace(loop_name,str(val))
                try:
                    text = eval(text.replace("]",""))
                except:
                    continue
                tail = node.tail
                node.clear()
                node.text = str(text)
                node.tail = tail
            instructions += [stmt for stmt in copy]
        data_queue = instructions + data_queue

    elif tag == "box":
        block = child.find(f"./{ns}block/{ns}block_content")
        data_queue = [stmt for stmt in block] + data_queue

    elif tag == "measure":
        _t = t()
        line = int(child.attrib["pos"])
        measured_qubit = child.find(f"./{ns}expr")
        store_name = child.find(f"./{ns}name")
        if measured_qubit.findall(f".//{ns}index/{ns}expr/{ns}operator[.=':']"):
            index = "".join(measured_qubit.find(f".//{ns}index").itertext())[1:-1]
            start, end = [int(x) for x in index.split(":")]
            q_name = "".join(measured_qubit.find(f"./{ns}name").itertext()).split("[")[0]
            name = "".join(store_name.find(f"./{ns}name").itertext()).split("[")[0]
            for i in range(start, end+1):
                qubits[q_name+f"[{i}]"]["actions"].append({"action":"measure","store":name+f"[{i}]","time":_t,"line":line} | get_ifs(ifs))
        else:
            qubit = "".join(measured_qubit.itertext())
            if qubit in qubits:
                qubits[qubit]["actions"].append({"action":"measure","store":"".join(store_name.itertext()),"time":_t,"line":line} | get_ifs(ifs))
            elif qubit + "[0]" in qubits:
                i = 0
                while qubit+f"[{i}]" in qubits:
                    qubits[qubit+f"[{i}]"]["actions"].append({"action":"measure","store":"".join(store_name.itertext())+f"[{i}]","time":_t,"line":line} | get_ifs(ifs))
                    i += 1

    elif tag == "barrier":
        _t = t()
        line = int(child.attrib["pos"])
        qargs = child.findall(f".//{ns}argument_list/{ns}argument")
        if len(qargs) > 0:
            for qarg in ["".join(arg.itertext()) for arg in qargs]:
                if qarg in qubits:
                    qubits[qarg]["actions"].append({"action":"barrier","time":_t,"line":line} | get_ifs(ifs))
                elif qarg+"[0]" in qubits:
                    for qubit in qubits:
                        if qubit.startswith(qarg):
                            qubits[qubit]["actions"].append({"action":"barrier","time":_t,"line":line} | get_ifs(ifs))
        else:
            for qubit in qubits:
                if qubit["type"] == "physical" and len(qubit["actions"]) == 0:
                    continue
                qubits[qubit]["actions"].append({"action":"barrier","time":_t,"line":line} | get_ifs(ifs))




# for qubit in qubits:
#     print(qubit)
#     for item in qubits[qubit]["actions"]:
#         print(f"\t{item}")

# for i in range(count.count):
#     for qubit in qubits:
#         for item in qubits[qubit]["actions"]:
#             if item["time"] == i:
#                 print(qubit,"->",item)
#     print()


time_array = {}
for i in range(count.count):
    time_array[i] = []
    print("TIME",i)
    for qubit in qubits:
        for item in qubits[qubit]["actions"]:
            if item["time"] == i:
                print(f"\t{qubit}->{item}")
                time_array[i].append((qubit,item))
#print(time_array)

qubits["_filename"] = sys.argv[1].replace("\\","/")

data = json.dumps(qubits,indent=4)
with open("out.json",'w') as file:
    file.write(data)


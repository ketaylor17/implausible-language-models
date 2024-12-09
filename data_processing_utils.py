import json

"""
functions for reading and writing data
"""

def save_to_json_file(list_of_stuff, filename):
    save_file = open(filename+".json", "w")
    json.dump(list_of_stuff, save_file)
    save_file.close()

def load_from_json_file(filename):
    with open(filename+'.json', 'r') as file:
        loaded_data = json.load(file)
    return loaded_data

"""
functions for processing stanza-generated Sentence objects into dictionaries
"""

# sentence is an array of dictionaries.
# adds an entry called 'children' to each dictionary, which references a list of ids of the children of that word/node.
# this makes tree traversal easier later.
# also moves words that have tuple ids to the end of the sentence (to avoid complications when indexing into word array).
# tuple words exist to denote contractions.
# ex. if sentence contains "it's" then there will be normal word entries for "it" and "'s", and a tuple word entry for "it's".
# we ignore tuple words when generating modified sentences but we keep them in the dataset in case we want to reference later. 
def add_child_relations_and_move_tuples(sentence):
    for word in sentence:
        word['children'] = []
    for word in sentence:
        if type(word['id'])==tuple:
            sentence.remove(word)
            sentence.append(word)
    for word in sentence:
        if type(word['id'])==tuple:
            continue
        parent_id = word['head']
        if parent_id != 0: # id is 0 if it's root of whole sentence
            sentence[parent_id-1]['children'].append(word['id'])

# convert from Stanza objects into Python dicts so we can save using json. 
# no information is lost compared to raw Stanza output.
# note: this deletes empty BabyLM "sentences" and expands BabyLM "sentences" which contain multiple complete sentences.
# so, length of docs != length of list_of_sentences, and that's fine.
def convert_list_of_stanza_docs_into_list_of_list_of_dicts(docs):
    list_of_sentences = []
    for doc in docs:
        for i in range(len(doc.sentences)): 
            # some "sentences" in BabyLM actually contain multiple complete sentences. We split them up with this for loop.
            sentence_array = doc.sentences[i].to_dict() # convert each word from Stanza word object to python dict
            add_child_relations_and_move_tuples(sentence_array)
            list_of_sentences.append(sentence_array)
    return list_of_sentences
            
"""
functions for processing out_arrs into a list of (modified) strings
note: use get_original_strings(out_arrs) rather than the original piece of babylm for consistency/parsing reasons
"""

# use this rather than the original strings from BabyLM so that spacing, etc. is constant across datasets
def get_original_strings(list_of_sentences):
    def make_sentence_into_array(sentence):
        return [word['text'] for word in sentence if (type(word['id']) not in [list, tuple])]
    return [' '.join(make_sentence_into_array(sentence)) for sentence in list_of_sentences]

# reverses everything including punctuation
def get_reversed_strings(list_of_sentences):
    def make_sentence_into_array(sentence):
        return [word['text'] for word in sentence if (type(word['id']) not in [list, tuple])]
    return [' '.join(make_sentence_into_array(sentence)[::-1]) for sentence in list_of_sentences]

# called as a subroutine in get_ordered_strings and also the head initial and head final methods
def get_root_id_of_sentence(sentence):
    root = 0
    for i, word in enumerate(sentence):
        if (type(word['id']) == tuple) or (type(word['id']) == list):
            continue
        if word['head'] == 0:
            root = i+1
    return root

# called as a subroutine in get_ordered_strings. can use on any subtree
# we want to keep exclamations at the beginning or end of a sentence/phrase (such   
#  as 'oh', 'yeah', '-', '?', etc.) where they are rather than permuting them
# also, in cases of multiple clauses joined by conjunctions (like 'and' or ','), we
#  want to leave the conjunction where it is and recurse into each clause separately.
# root is not included in any of the arrays and needs to be added back in later
prefix_deprels = ['punct', 'discourse', 'cc', 'parataxis', 'list', 'conj', 'mark']
suffix_deprels = ['punct', 'discourse', 'cc', 'parataxis', 'list', 'conj']
def split_into_prefix_body_suffix(sentence, child_array, root_id):
    prefix_array = []
    suffix_array = []
    # get things in prefix and put them in prefix array
    for (child_id, child_string) in child_array:
        if child_id > root_id:
            break
        if sentence[child_id-1]['deprel'] in prefix_deprels:
            prefix_array.append((child_id, child_string))
        else:
            break
    # get things in suffix and put them in suffix array
    for (child_id, child_string) in child_array[::-1]:
        if child_id < root_id:
            break
        if sentence[child_id-1]['deprel'] in suffix_deprels:
            suffix_array = [(child_id, child_string)] + suffix_array
        else:
            break
    body_array = child_array[len(prefix_array):len(child_array)-len(suffix_array)]
    return prefix_array, body_array, suffix_array

# called as a subroutine in get_ordered_strings.
# only used when root of subtree is a verb!
# root is not included in any of the arrays and needs to be added back in later
subject_deprels = ['nsubj','csubj','nsubj:outer','nsubj:pass']
object_deprels = ['obj','iobj','ccomp','xcomp']
def split_into_subject_verb_object(sentence, body_array):
    subject_array = []
    verb_array = []
    object_array = []
    for (child_id, child_string) in body_array:
        deprel = sentence[child_id-1]['deprel']
        if deprel in subject_deprels:
            subject_array.append((child_id, child_string))
        elif deprel in object_deprels:
            object_array.append((child_id, child_string))
        else:
            verb_array.append((child_id, child_string))
    return subject_array, verb_array, object_array

# called as a subroutine in get_ordered_strings.
# used when one of the children is a copula (i.e. some form of 'to be')
# root is not included in any of the arrays and needs to be added back in later
def split_subtree_with_copula_into_subject_verb_object(sentence, body_array):
    subject_array = []
    verb_array = []
    object_array = []
    for (child_id, child_string) in body_array:
        deprel = sentence[child_id-1]['deprel']
        if deprel in subject_deprels:
            subject_array.append((child_id, child_string))
        elif deprel == 'cop':
            verb_array.append((child_id, child_string))
        else: # for subtrees with copula, the main object of the copula is the root. so add to object arrary by default
            object_array.append((child_id, child_string))
    return subject_array, verb_array, object_array

# called as a subroutine in get_ordered_strings.
# hopefully self-explanatory
def put_in_order(subject_array, verb_array, object_array, order):
    s = subject_array
    v = verb_array
    o = object_array
    if order=='svo':
        return s+v+o
    if order=='sov':
        return s+o+v
    if order=='vso':
        return v+s+o
    if order=='vos':
        return v+o+s
    if order=='osv':
        return o+s+v
    if order=='ovs':
        return o+v+s
    print('invalid order')

# recursively splits each subtree into subject, verb, and object subphrases and permutes them to match 'order' parameter
# if the subtree does not contain a verb, then it is left alone, but we still recurse into its children
def get_ordered_strings(list_of_sentences, order):
    def get_ordered_string(sentence): # subroutine for one sentence
        def make_ordered(root_id): # subroutine for one subtree
            root_string = sentence[root_id-1]['text']
            child_id_array = sentence[root_id-1]['children']
            if len(child_id_array) == 0:
                return root_string
            child_array = [(child_id, make_ordered(child_id)) for child_id in child_id_array]
            root_array = [(root_id, root_string)]
            # when subtree contains copula and has verb as root, presence of copula dominates for how it should be parsed.
            if 'cop' in [sentence[child_id-1]['deprel'] for (child_id, child_string) in child_array]:
                prefix_array, body_array, suffix_array = split_into_prefix_body_suffix(sentence, child_array, root_id)
                subject_array, verb_array, object_array = split_subtree_with_copula_into_subject_verb_object(sentence, body_array)
                object_array = sorted(object_array + root_array) # root is object
                ordered_array = put_in_order(subject_array, verb_array, object_array, order)
                whole_subtree_array = prefix_array + ordered_array + suffix_array
                return ' '.join([t[1] for t in whole_subtree_array])
            # if no copula, then check for root verb
            elif sentence[root_id-1]['upos']=='VERB':
                prefix_array, body_array, suffix_array = split_into_prefix_body_suffix(sentence, child_array, root_id)
                subject_array, verb_array, object_array = split_into_subject_verb_object(sentence, body_array)
                verb_array = sorted(verb_array + root_array) # root is verb
                ordered_array = put_in_order(subject_array, verb_array, object_array, order)
                whole_subtree_array = prefix_array + ordered_array + suffix_array
                return ' '.join([t[1] for t in whole_subtree_array])
            # if subtree is not a verb phrase, then keep it the same (but still recurse on its children)
            else:
                whole_subtree_array = sorted(child_array + root_array, key = lambda x : x[0])
                return ' '.join([t[1] for t in whole_subtree_array])
        overall_root = get_root_id_of_sentence(sentence) # identify which node to start the recursion at
        return make_ordered(overall_root) # recurse
    return [get_ordered_string(sentence) for sentence in list_of_sentences]

# puts head/root of each subtree (as determined by Universal Dependencies/Stanza) at the beginning of that subtree
def get_head_initial_strings(list_of_sentences):
    def get_head_initial_string(sentence): # subroutine for one sentence
        def make_hi(root_id): # subroutine for one subtree
            root_string = sentence[root_id-1]['text']
            child_id_array = sentence[root_id-1]['children']
            if len(child_id_array) == 0:
                return root_string
            child_array = [(child_id, make_hi(child_id)) for child_id in child_id_array]
            root_array = [(root_id, root_string)]
            prefix_array, body_array, suffix_array = split_into_prefix_body_suffix(sentence, child_array, root_id)
            # always put root first, regardless of what kind of phrase it is
            whole_subtree_array = prefix_array + root_array + body_array + suffix_array
            return ' '.join([t[1] for t in whole_subtree_array])
        overall_root = get_root_id_of_sentence(sentence) # identify which node to start the recursion at
        return make_hi(overall_root) # recurse
    return [get_head_initial_string(sentence) for sentence in list_of_sentences]

# puts head/root of each subtree (as determined by Universal Dependencies/Stanza) at the end of that subtree
def get_head_final_strings(list_of_sentences):
    def get_head_final_string(sentence): # subroutine for one sentence
        def make_hf(root_id): # subroutine for one subtree
            root_string = sentence[root_id-1]['text']
            child_id_array = sentence[root_id-1]['children']
            if len(child_id_array) == 0:
                return root_string
            child_array = [(child_id, make_hf(child_id)) for child_id in child_id_array]
            root_array = [(root_id, root_string)]
            prefix_array, body_array, suffix_array = split_into_prefix_body_suffix(sentence, child_array, root_id)
            # always put root last, regardless of what kind of phrase it is
            whole_subtree_array = prefix_array + body_array + root_array + suffix_array
            return ' '.join([t[1] for t in whole_subtree_array])
        overall_root = get_root_id_of_sentence(sentence) # identify which node to start the recursion at
        return make_hf(overall_root) # recurse
    return [get_head_final_string(sentence) for sentence in list_of_sentences]
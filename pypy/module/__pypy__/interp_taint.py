
def get_taint(space, w_obj):
    return w_obj.gettaint(space)

def clear_taint(space, w_obj):
    return w_obj.cleartaint(space)

def add_taint(space, w_obj, w_taint_int):
    return w_obj.addtaint(space, w_taint_int)

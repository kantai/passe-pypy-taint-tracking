
def get_control_taint(space):
    ec = space.getexecutioncontext()
    f = ec.gettopframe_nohidden()
    return space.wrap(f.taint_space.get_taints())

def get_taint(space, w_obj):
    return w_obj.gettaint(space)

def clear_taint(space, w_obj):
    return w_obj.cleartaint(space)

def add_taint(space, w_obj, w_taint_int):
    return w_obj.addtaint(space, w_taint_int)


def get_control_taint(space):
    ec = space.getexecutioncontext()
    f = ec.gettopframe_nohidden()
    return space.newlist([space.newint(z) for z in
                          f.taint_space.get_taints().keys()])

def get_taint(space, w_obj):
    return w_obj.gettaint(space)

def clear_taint(space, w_obj):
    return w_obj.cleartaint(space)

def add_taint(space, w_obj, w_taint_int):
    return w_obj.addtaint(space, w_taint_int)

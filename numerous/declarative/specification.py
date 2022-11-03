from __future__ import annotations

from enum import Enum
from uuid import uuid4
import types
import dataclasses
from .context_managers import _active_mappings, _active_subsystem, NoManagerContextActiveException
from .variables import Variable, Operations, PartialResult
from .watcher import watcher, WatchedObject, WatchObjectMeta

from numerous.engine.system import Subsystem, Item
from numerous.engine.variables import VariableType
from numerous.multiphysics.equation_base import EquationBase
from numerous.multiphysics.equation_decorators import add_equation


def path_to_str(var):
    if var is None:
        return "None"
    return ".".join(list(var.path.path.values())[-1])


def print_map(var):
    print(path_to_str(var) + ": " + path_to_str(var.mapping) + ", " + str([path_to_str(v) for v in var.sum_mapping]))

class MappingOutsideMappingContextError(Exception):
    ...

class ScopeSpec(WatchedObject):
    """
       Specification of a scope in a module. Extend this class and create class variables to define a new specifcation of the variables in a namespace for a module.
   """



    def __init__(self, parent_path=[], new_var_ids=False):

        super(ScopeSpec, self).__init__()

        self._variables = {}
        self._host: ModuleParent = None

        self._equations = []

        class_var = {}

        for b in self.__class__.__bases__:
            class_var.update(b.__dict__)

        class_var.update(self.__class__.__dict__)

        for k, v in class_var.items():

            if isinstance(v, Variable):
                # instance = v.instance(id=".".join(parent_path+[k]), name=k)
                instance = v.instance(id=str(uuid4()) if new_var_ids else v.id, name=k, host=self)
                #instance = v.instance(id=str(uuid4()), name=k, host=self)
                setattr(self, k, instance)

                self._variables[k] = instance

    def get_child_attr(self, child):
        for attr, val in self.__dict__.items():
            if val == child:
                return attr

        raise ModuleNotFoundError(f"{child} not an attribute on {self}")
    def get_path(self, child, parent):
        _attr = self.get_child_attr(child)
        if self == parent:
            path = [_attr]
            return path
        else:
            path = self._host.get_path(self, parent) + [_attr]
            return path
    def __setattr__(self, key, value, clone=False):

        if clone:
            super(ScopeSpec, self).__setattr__(key, value)
            return
        elif isinstance(value, PartialResult) and not isinstance(value, Variable):
            if value.op == Operations.ADD and value.arguments[0] == getattr(self, key) and isinstance(
                    value.arguments[1],
                    Variable):
                try:
                    mapping_manager = _active_mappings.get_active_manager_context()
                    mapping_manager.add(value.arguments[0], value.arguments[1])
                except NoManagerContextActiveException:
                    raise MappingOutsideMappingContextError(
                        "Mapping outside mapping context not possible. Place mappings inside a mapping context using 'create_mappings' context manager.")

            else:
                raise ValueError('Partial result not matching additive mapping.')
        elif hasattr(self, '_variables') and key in self._variables:
            try:
                mapping_context: ModuleMappings = _active_mappings.get_active_manager_context()
            except NoManagerContextActiveException:
                raise MappingOutsideMappingContextError("Mapping outside mapping context not possible. Place mappings inside a mapping context using 'create_mappings' context manager.")
            map_to = getattr(self, key)
            mapping_context.assign(map_to, value)

        else:
            super(ScopeSpec, self).__setattr__(key, value)

    def _instance(self, parent_path=[]):
        return self.__class__(parent_path)

    def _clone(self, host=None):
        clone = self.__class__(new_var_ids=True)
        clone._equations = self._equations
        clone.set_host(host)
        # var_list = list(clone.__dict__.items())
        # for var, val in var_list:
        #    if isinstance(val, Variable):
        #        clone.__setattr__(var, val.clone(id=str(uuid4()), name=val.name), clone=True)

        return clone

    def set_host(self, host):
        self._host = host
    def _generate_variables(self, equation):
        ...

class ItemNotAssignedError(Exception):
    ...

class NoSuchItemInSpec(Exception):
    ...

class UnrecognizedItemSpec(Exception):
    ...

class ItemsSpec(WatchedObject):
    """
    Specification of the items in a module. Extend this class and create class variables to define a new specifcation of items for a module.
    """

    _initialized = False

    def __init__(self):

        super(ItemsSpec, self).__init__()

        self._items = {}
        self._host = None

        annotations = self.__class__.__annotations__
        #a = get_type_hints(self.__class__)
        for var, hint in annotations.items():
            if not hasattr(self, var):

                self._handle_item(var, hint)

            #self._items[var] = getattr(self, var)



        vallist = list(self.__class__.__dict__.items())# + list(self._items.items())
        for var, val in vallist:
            self._handle_item(var, val)

        self._initialized = True

    def set_host(self, host):
        self._host = host
        for name, item in self._items.items():
            if isinstance(item, Module) or isinstance(item, ModuleSpec):
                item.set_host(self)
    def get_child_attr(self, child):
        for attr, val in self.__dict__.items():
            if val == child:
                return attr

        raise ModuleNotFoundError(f"{child} not an attribute on {self}")

    def get_path(self, child, parent):

        _attr = self.get_child_attr(child)
        if self == parent:

            path = [_attr]
            return path
        else:
            path = self._host.get_path(self, parent) + [_attr]
            return path

    def _clone(self):
        clone_ = self.__class__()
        clone_.set_host(self._host)
        return clone_

    def _handle_item(self, var, val):

        if isinstance(val, Module):
            self._items[var] = val

            raise NotImplementedError()

        elif inspect.isclass(val) and issubclass(val, Module) or val.__class__.__name__== "_AnnotatedAlias":

            clone_ = val.clone_tree(self._host)

            setattr(self, var, clone_)
            self._items[var] = clone_

        elif isinstance(val, ModuleSpec):
            raise NotImplementedError()
        #else:
        #    raise UnrecognizedItemSpec(f"The class {val.__class__.__name__} cannot be used as an item for {var}.")

    def _check_assigned(self):
        for name, item in self._items.items():
            item_ = getattr(self, name)
            if inspect.isclass(item_):
                raise ItemNotAssignedError(f'Item <{name}> is not assigned properly, value is a class {item_}.')
            elif isinstance(item_, ModuleSpec):
                raise ItemNotAssignedError(f'Item <{name}> is still a {item_.__class__} object, meaning it as not been assigned during Module initialization.')
            elif item_ is None:
                raise ItemNotAssignedError(f'Item <{name}> is not assigned, value is {item_}.')

            if not isinstance(item_, Module):
                raise ItemNotAssignedError(f"The item <{item_}> is not a Module but instead <{item_.__class__.__name__}>")


    def finalize(self):
        """
        Finalize this module. Checks if all items from item specifications have been assigned.
        """
        for name, item in self._items.items():
            item_ = getattr(self, name)

            if isinstance(item_, Module):
                item_.finalize(top=False)
            if isinstance(item_, ModuleSpec):
                item_.finalize()

        self._check_assigned()
        
        self.attach()

    def __setattr__(self, key, value):
        if self._initialized and key!="_items" and not hasattr(self,key):
            raise NoSuchItemInSpec(f"ItemsSpec {self.__class__.__name__} class has no item {key}. Please add the item to the ItemsSpec class.")
        super(ItemsSpec, self).__setattr__(key,value)



class ModuleSpec(WatchedObject):

    def __init__(self, module_cls: object):

        super(ModuleSpec, self).__init__()



        self.module_cls = module_cls
        self._item_specs = {}
        self._namespaces = {}
        self._finalized = False
        self._host = None

        class_var = {}

        for b in self.module_cls.__class__.__bases__:
            class_var.update(b.__dict__)

        class_var.update(self.module_cls.__dict__)

        for k, v in class_var.items():

            if isinstance(v, ItemsSpec):
                clone_ = v._clone()
                self._item_specs[k] = clone_
                setattr(self, k, clone_)

            elif isinstance(v, ScopeSpec):
                clone_ = v._clone(host=self)
                self._namespaces[k] = clone_
                setattr(self, k, clone_)


    def set_host(self, host):
        self._host = host
    def get_child_attr(self, child):
        for attr, val in self.__dict__.items():
            if val == child:
                return attr

        raise ModuleNotFoundError(f"{child} not an attribute on {self}")
    def get_path(self, child, parent):
        _attr = self.get_child_attr(child)
        if self == parent:
            path = [_attr]
            return path
        else:
            path = self._host.get_path(self, parent) + [_attr]

            return path

    def finalize(self):
        self._finalized = True

        for item_spec in self._item_specs.values():
            item_spec.finalize()

        for scope_spec in self._namespaces.values():
            scope_spec.attach()

        super(ModuleSpec, self).finalize()

import inspect
def allow_implicit(func):
    sign = inspect.signature(func)


    def check_implicit(*args, **kwargs):

        if len(args)>1 and isinstance(item:=args[1], Item):
            _kwargs = {}
            _args = []
            for n, p in sign.parameters.items():
                if n != "self":
                    val = getattr(getattr(item, 'variables'),n)
                    if n in kwargs:

                        _kwargs[n] = val
                    else:
                        _args.append(val)


            func(args[0], *_args, **kwargs)
        else:
            func(*args, **kwargs)


    return check_implicit


class EquationSpec(WatchedObject):
    """
       Specification of an equation in a module. Use this as a decorator for your methods implementing the equations in a module.
   """
    def __init__(self, scope: ScopeSpec):

        super(EquationSpec, self).__init__()
        """
        Create an equation specification.

        Will add the equation to the scope passed as the argument
        """
        self.scope = scope
        self.func = None

    def __call__(self, func):
        self.func = func
        self.scope._equations.append(self)



        return self.func


@dataclasses.dataclass
class ResolveInfo:
    resolved: bool = False
    path: list = dataclasses.field(default_factory=lambda: list())
    name: str = ""


def resolve_variable_(obj, resolve_var: Variable) -> ResolveInfo:

    if isinstance(obj, Module) or isinstance(obj, Obj):
        if obj._scopes is not None:

            for scope_name, scope in obj._scopes.items():

                for var_name, var in scope._variables.items():

                    if var.id == resolve_var.id:

                        return ResolveInfo(resolved=True, path=[scope_name], name=var_name)

        if obj._item_specs is not None:

            for item_name, item in obj._item_specs.items():
                resolve = resolve_variable_(item, resolve_var)
                if resolve.resolved:
                    resolve.path = [item_name] + resolve.path
                    return resolve


    elif (inspect.isclass(obj) and issubclass(obj, Module)):
        for attr_name, attr_val in obj.__dict__.items():
            if isinstance(attr_val, ScopeSpec):

                for var_name, var in attr_val._variables.items():

                    if var.id == resolve_var.id:
                        return ResolveInfo(resolved=True, path= [attr_name], name=var_name)
            if isinstance(attr_val, ItemsSpec):
                resolve = resolve_variable_(attr_val, resolve_var)
                if resolve.resolved:
                    resolve.path = [attr_name] + resolve.path
                    return resolve


    elif isinstance(obj, ItemsSpec):
        for item_name, item in obj._items.items():
            resolve = resolve_variable_(item, resolve_var)
            if resolve.resolved:
                resolve.path = [item_name] + resolve.path
                return resolve

    elif isinstance(obj, ModuleSpec):

        for attr_name, attr_val in obj._namespaces.items():
            if isinstance(attr_val, ScopeSpec):

                for var_name, var in attr_val._variables.items():
                    if var.id == resolve_var.id:

                        return ResolveInfo(resolved=True, path=[attr_name], name=var_name)

        for item_name, item in obj._item_specs.items():

            resolve = resolve_variable_(item, resolve_var)
            if resolve.resolved:
                resolve.path = [item_name] + resolve.path
                return resolve


    else:
        raise MappingFailed('Not a compatible object '+str(obj))

    #raise MappingFailed(
    #    f"Could not find variable with id <{resolve_var.id}> and name <{resolve_var.name}> in scope spec <{attr_name}> of module spec <{obj.module_cls.__name__}>")

    return ResolveInfo()

def resolve_variable(obj, resolve_var: Variable) -> ResolveInfo:
    resolve = resolve_variable_(obj, resolve_var)

    if not resolve.resolved:
        raise MappingFailed(f"Could not find <{resolve_var.id}, {resolve_var.name}> in <{obj}>")
    return resolve

def recursive_get_attr(obj, attr_list):

    attr_ = getattr(obj, attr_list[0])

    if len(attr_list)>1:
        return recursive_get_attr(attr_, attr_list[1:])
    else:
        return attr_


class MappingFailed(Exception):
    ...


class MappedToFixedError(Exception):
    ...


class NotMappedError(Exception):
    ...


class FixedMappedError(Exception):
    ...


class ModuleParent(Subsystem, EquationBase, WatchedObject):

    tag = None
    _finalized = False
    _mapping_groups = {}
    _item_specs = {}
    _scope_specs = {}
    _resolved_mappings = []
    _must_map_variables = []
    _fixed_variables = []
    _scopes = {}

    def __repr__(self):
        return object.__repr__(self)
    def __init__(self, *args, **kwargs):
        super(ModuleParent, self).__init__(*args, **kwargs)

        self._host = None

        #self._scope_specs = self._scope_specs.copy()
        for k, v in self._scope_specs.items():
            clone_ = v._clone(host=self)
            v.attach()
            watcher.add_watched_object(clone_)
            setattr(self, k, clone_)

            #    v.check_assigned()
            self.add_scope(self, k, clone_, kwargs)



    def check_variables(self):

        for v in self._must_map_variables:

            resolve = resolve_variable(self, v)

            var = getattr(recursive_get_attr(self, resolve.path), resolve.name)

            if var.mapping is None:
                raise NotMappedError(f"The variable {var.path.primary_path} is set must be mapped, but is not mapped!")

        for v in self._fixed_variables:
            resolve = resolve_variable(self, v)
            var = getattr(recursive_get_attr(self, resolve.path), resolve.name)

            if var.mapping is not None:
                raise FixedMappedError(
                    f"The variable {var.path.primary_path} is fixed, but mapped to another variable!")

    def _finalize(self, top=True):
        if not self._finalized:

            # self._scope_specs.update(self.__dict__)

            for itemspec_name, itemspec in self._item_specs.items():
                itemspec.finalize()

            for item in self.registered_items.values():
                item.finalize(top=False)

            for resolved_mapping in self._resolved_mappings:
                resolved_from = resolved_mapping[1]
                resolved_to = resolved_mapping[0]
                map_type = resolved_mapping[2]
                if map_type == MappingTypes.ASSIGN:

                    try:

                        to_attr = recursive_get_attr(self, resolved_to.path)
                    except AttributeError as ae:
                        raise MappingFailed(f"!")

                    try:
                        from_attr = getattr(recursive_get_attr(self, resolved_from.path[:-1]),
                                            resolved_from.path[-1])
                    except AttributeError as ae:
                        raise MappingFailed(
                            f"The obj_ect {self}, {resolved_from.path} has no variable {resolved_from.name}")
                    except IndexError:
                        raise MappingFailed(
                            f"The obj_ect {self}, {resolved_from.path} has no variable {resolved_from.name}")

                    setattr(to_attr, resolved_to.path[-1], from_attr)
                elif map_type == MappingTypes.ADD:
                    try:
                        to_attr = recursive_get_attr(self, resolved_to.path)
                    except AttributeError as ae:

                        raise MappingFailed(
                            f"The namespace {'.'.join([str(s) for s in [self] + resolved_to.path[:-1]])} does not have a variable {resolved_to.path[-1]}.")

                    try:
                        from_attr = getattr(recursive_get_attr(self, resolved_from.path[:-1]),
                                            resolved_from.path[-1])
                    except AttributeError as ae:
                        raise MappingFailed(
                            f"The obj_ect {self}, {resolved_from.path} has no variable {resolved_from.name}")

                    to_attr.__iadd__(from_attr)

                else:
                    raise ValueError('Unknown mapping type: ', map_type)


            self.check_variables()

            self._finalized = True
            self.attach()
            if top:
                watcher.finalize()

    def prefinalize(self):
        ...

    def finalize(self, top=True):

        self.prefinalize()
        self._finalize(top=top)


    @classmethod
    def add_scope(cls, obj, namespace, scope, values: dict):

        ns = obj.create_namespace(namespace)
        obj._scopes[namespace] = scope
        setattr(obj, namespace, ns)

        class Eq(EquationBase):

            tag = namespace + '_eq'

        eq_ = Eq()

        for eq_spec in scope._equations:
            eq_func = eq_spec.func
            eq_func.__self__ = obj
            eq_func_dec = add_equation(eq_, eq_func)
            eq_spec.attach()


        prescope = list(scope.__dict__.items())

        for v_name, v_ in prescope:

            if isinstance(v_, Variable):

                if v_name in values:
                    val = values.pop(v_name)

                else:
                    val = v_.value

                if v_.fixed:
                    obj._fixed_variables.append(v_)
                if v_.must_map:
                    obj._must_map_variables.append(v_)

                if v_.construct:
                    if v_.type == VariableType.PARAMETER:
                        var = eq_.add_parameter(v_name, val, logger_level=None, alias=None, integrate=v_.integrate)

                    else:
                        var = eq_.add_variable(v_name, val, var_type=v_.type, logger_level=None, alias=None)

                #    v_.set_variable(var)

        scope._generate_variables(eq_)
        ns.add_equations([eq_])
        scope.attach()

    @classmethod
    def clone_tree(cls, host):
        clone = ModuleSpec(cls)
        return clone

    def get_child_attr(self, child):
        for attr, val in self.__dict__.items():
            if val == child:
                return attr

        raise ModuleNotFoundError(f"{child} not an attribute on {self}")

    def get_path(self, parent):

        if self._host == parent:
            return [self._host.get_child_attr(parent, self)]
        else:

            path = self._host.get_path(self, parent)
            return path


    def set_host(self, host):
        self._host = host

class DuplicateItemError(Exception):
    ...


class RegisterHelper:


    def __init__(self):
        self._items = {}

    def register_item(self, item):
        if item.tag in self._items:
            raise DuplicateItemError(f"An item with tag {item.tag} already registered.")
        self._items[item.tag] = item

    def get_items(self):
        return self._items


class Obj:
    def __init__(self, scope_specs, items_specs):
        self._item_specs = items_specs
        self._scopes = scope_specs

class ModuleMeta(WatchObjectMeta):

    def __init__(self, class_name: str, base_classes: tuple, __dict__: dict, **kwargs):
        super(ModuleMeta, self).__init__(class_name, base_classes, __dict__, **kwargs)

    def __call__(cls, *args, **kwargs):

        #cls.__init__ = wrap
        parent_module = _active_subsystem.get_active_manager_context(ignore_no_context=True)

        register_helper = RegisterHelper()

        items_specs = {}
        scope_specs = {}
        mapping_groups = {}
        _objects = {}


        for b in list(cls.__bases__)+[cls]:
            _objects.update(b.__dict__)

        obj_ = Obj(scope_specs, items_specs)





        for attr, var in _objects.items():
            if isinstance(var, ItemsSpec):
                var.set_host(cls)
                clone_ = var._clone()
                items_specs[attr] = clone_

                #watcher.add_watched_object(var)
                watcher.add_watched_object(clone_)
                ...

            elif isinstance(var, ScopeSpec):
                var.set_host(cls)
                scope_specs[attr] = var
                watcher.add_watched_object(var)
                [watcher.add_watched_object(e) for e in var._equations]

        _resolved_mappings = []
        for attr, var in _objects.items():

            if isinstance(var, ModuleMappings):
                mapping_groups[attr] = var
                watcher.add_watched_object(var)

                for mapping_ in var.mappings:

                    mapto = mapping_[0]
                    mapfrom = mapping_[1]

                    map_type = mapping_[2]


                    resolved_to = ResolveInfo(True, mapto.get_rel_path(cls), "")
                    to_ = ".".join(resolved_to.path)
                    resolved_from = ResolveInfo(True, mapfrom.get_rel_path(cls), "")

                    from_ = ".".join(resolved_from.path)

                    print("mapping: "+from_+" -> "+to_)

                    _resolved_mappings.append((resolved_to, resolved_from, map_type))
                var.attach()



        org_init = cls.__init__
        def wrap(self, *args, **kwargs):

            self._resolved_mappings = _resolved_mappings
            self._must_map_variables = []
            self._fixed_variables = []
            self._scopes = {}
            self._scope_specs = scope_specs
            self._item_specs = items_specs

            for item_name, item in items_specs.items():
                setattr(self, item_name, item)

            self._mapping_groups = mapping_groups
            org_init(self, *args, **kwargs)




        _active_subsystem.clear_active_manager_context(parent_module)
        _active_subsystem.set_active_manager_context(register_helper)
        cls.__init__ = wrap
        instance = super(ModuleMeta, cls).__call__(*args, **kwargs)
        cls.__init__ = org_init
        _active_subsystem.clear_active_manager_context(register_helper)
        _active_subsystem.set_active_manager_context(parent_module)

        if cls.tag is not None and instance.tag is None:
            instance.tag = cls.tag

        if instance.tag is None:
            instance.tag = cls.__name__.lower()

        [instance.register_item(i) for i in register_helper.get_items().values()]

        if isinstance(parent_module, RegisterHelper) or isinstance(parent_module, Subsystem):
            parent_module.register_item(instance)

        instance._item_specs = items_specs
        instance._scope_specs = scope_specs
        instance._mapping_groups = mapping_groups

        watcher.add_watched_object(instance)

        return instance
class Module(ModuleParent, metaclass=ModuleMeta):
    ...

class MappingTypes(Enum):

    ASSIGN = 0
    ADD = 1


class ModuleMappings(WatchedObject):

    mappings = []

    def __init__(self, *args):

        super(ModuleMappings, self).__init__()

        self.mappings = list(args)

    def __enter__(self):
        _active_mappings.set_active_manager_context(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _active_mappings.clear_active_manager_context(self)

    def assign(self, a, b):
        if not isinstance(a, Variable):
            raise TypeError(f"a is not a Variable, but {a.__class__.__name__}")
        if not isinstance(b, Variable):
            raise TypeError(f"b is not a Variable, but {b.__class__.__name__}")
        self.mappings.append((a, b, MappingTypes.ASSIGN))
        a.mapped_to.append(b)


    def add(self, a, b):
        self.mappings.append((a, b, MappingTypes.ADD))
        a.mapped_to.append(b)


def create_mappings(*args):

    return ModuleMappings(*args)

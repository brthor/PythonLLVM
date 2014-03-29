#!/usr/bin/env python

import os, sys
import re
import compiler

import llvm.core
# original=commented
from VecTypes import *
from MUDA import *
from TypeInference import *
from SymbolTable import *

symbolTable    = SymbolTable()
typer          = TypeInference(symbolTable)

llTruthType    = llvm.core.Type.int(1)
llVoidType     = llvm.core.Type.void()
llIntType      = llvm.core.Type.int()
llFloatType    = llvm.core.Type.float()
llFVec4Type    = llvm.core.Type.vector(llFloatType, 4)
llFVec4PtrType = llvm.core.Type.pointer(llFVec4Type)
llIVec4Type    = llvm.core.Type.vector(llIntType, 4)
# converts from python to LLVM type
def toLLVMTy(ty):

    if ty is None:
        return llVoidType
    if ty is list:
        raise Exception("need to find list length yourself")
    d = {
          float : llFloatType
        , int   : llIntType
        , vec   : llFVec4Type
        , void  : llVoidType
        }

    if d.has_key(ty):
        return d[ty]
    raise Exception("pyllvm err: Unknown type:", ty)

class CodeGenLLVM:
    """
    LLVM CodeGen class
    """

    def __init__(self):
        print ";----" + sys._getframe().f_code.co_name + "----"

        self.body             = ""
        self.globalscope      = ""

        self.module           = llvm.core.Module.new("module")
        self.funcs            = []
        self.func             = None # Current function
        self.builder          = None

        self.currFuncRetType  = None
        self.currListFuncRet  = (None, 0)
        self.prevFuncRetNode  = None    # for reporiting err

        self.externals        = {}
        self.newline          = None
        self.printf           = None
        self.vec              = None
    def visitModule(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        # emitExternalSymbols() should be called before self.visit(node.node)
        self.emitExternalSymbols()
        
        self.emitPrint()

        self.visit(node.node)
        #print self.module   # Output LLVM code to stdout.
        #print self.emitCommonHeader()

    def getString(self):
        return self.module
    
    def mkGlobalStr(self, name, gstr):
        stringConst = llvm.core.Constant.stringz(gstr) # zero terminated --> stringz instead of string
        string = self.module.add_global_variable(stringConst.type, name)
        string.initializer = stringConst
        string.global_constant = True
        string.linkage = llvm.core.LINKAGE_INTERNAL # not strictly necessary here
        return string
    # source = http://code2code.wordpress.com/tag/llvm-py/ 
    def emitPrint(self):
     
        # add a prototype for printf
        funcType = llvm.core.Type.function(llIntType, [llvm.core.Type.pointer(llvm.core.Type.int(8))], True)
        self.printf = self.module.add_function(funcType, 'printf')

        # create global constants for printf string
        string_i = self.mkGlobalStr('__strInt', '%d ')
        string_f = self.mkGlobalStr('__strFloat', "%f ")
        self.newline = self.mkGlobalStr('__strNl', '\n')
        self.vec = self.mkGlobalStr('__strVec', 'vec: ')
 
        # create functions for print 
        funcType = llvm.core.Type.function(llVoidType, [llIntType])
        printInt = self.module.add_function(funcType, 'printInt')
        self._printInt = printInt
        f_funcType = llvm.core.Type.function(llVoidType, [llFloatType])
        printFloat = self.module.add_function(f_funcType, 'printFloat')
        self._printFloat = printFloat

        # create a block and a builder for print functions
        bb = printInt.append_basic_block('ib')
        b = llvm.core.Builder.new(bb)
        
        # address calculation
        idx = [llvm.core.Constant.int(llvm.core.Type.int(32), 0), llvm.core.Constant.int(llvm.core.Type.int(32), 0)] # the first index get's us past the global variable (which is a pointer) to the string; the second index is the offset inside the string we want to access
        realAddr_i = string_i.gep(idx)
        realAddr_f = string_f.gep(idx)
 
        # call printf for int
        b.call(self.printf, [realAddr_i, printInt.args[0]])
        b.ret_void()
        # call printf for float
        bf = printFloat.append_basic_block('fb')
        b.position_at_end(bf)
        d = b.fpext(printFloat.args[0], llvm.core.Type.double(), 'ftmp')
        b.call(self.printf, [realAddr_f, d])
        b.ret_void()

 
    def visitPrint(self, node):
        return None 


    def helpPrint(self, n):
        ty = typer.inferType(n)
        lln = self.visit(n)
        if(ty==int):
            return self.builder.call(self._printInt, [lln])
        if(ty==float):
            return self.builder.call(self._printFloat, [lln])
        # for now prints vec(1) as 4
        elif(ty==vec):
            # print 'vec'
            idx = [llvm.core.Constant.int(llvm.core.Type.int(32), 0), llvm.core.Constant.int(llvm.core.Type.int(32), 0)]
            realAddr_v = self.vec.gep(idx)
            self.builder.call(self.printf, [realAddr_v])
            # print content
            for i in range(4):
                i0 = llvm.core.Constant.int(llIntType, i);
                tmp0  = symbolTable.genUniqueSymbol(float)
                le0   = self.builder.extract_element(lln, i0, tmp0.name)
                self.builder.call(self._printFloat, [le0])
        elif(ty==list):
            # if is List, can find dimensions directly. If var can look it up
            #TODO-d: change to array instead of vec
            if isinstance(n, compiler.ast.List):
                lenList = len(n.nodes)
                tyList = typer.inferType(n.nodes[0])
            elif isinstance(n, compiler.ast.Name):
                tyList, lenList = symbolTable.find(n.name).getDim()
            elif isinstance(n, compiler.ast.CallFunc):
                 if not isinstance(n.node, compiler.ast.Name):
                     raise Exception("haven't implemented anonymous functions")
                 tyList, lenList = symbolTable.find(n.node.name).getDim()
            else:
                raise Exception("haven't implemented printing results of lists nonname/list/func")
            zero = llvm.core.Constant.int(llIntType, 0)
            for i in range(lenList):
                index = llvm.core.Constant.int(llIntType, i)
                tmp0  = symbolTable.genUniqueSymbol(float)
                #TODO-d: change to array
                l = self.builder.gep(lln, [zero, index])
                le0 = self.builder.load(l, tmp0.name)


                if( tyList == int):
                    self.builder.call(self._printInt, [le0])
                elif( tyList == float):
                    self.builder.call(self._printFloat, [le0])
                else:
                    raise Exception("haven't implemented lists of lists")
        else:
            raise Exception("haven't implemented printing of type: ", ty)
    def visitPrintnl(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        for n in node.nodes:
            if ( isinstance(n, compiler.ast.Tuple) ):
                [self.helpPrint(z) for z in n.nodes]
                break
            self.helpPrint(n)


        # print newline
        idx = [llvm.core.Constant.int(llvm.core.Type.int(32), 0), llvm.core.Constant.int(llvm.core.Type.int(32), 0)]
        realAddr_nl = self.newline.gep(idx)
        self.builder.call(self.printf, [realAddr_nl])

    def emitMakeArray(self, node):
        # super horrible malloc hack for returning arrays
        if isinstance(node, compiler.ast.List):
            self.currFuncRetList = (typer.inferType(node.nodes[0]), len(node.nodes))
        elif isinstance(node, compiler.ast.Name):
            self.currFuncRetList = symbolTable.find(node.name).getDim()
        elif isinstance(node, compiler.ast.CallFunc):
            self.currFuncRetList = symbolTable.find(node.node.name).getDim()
        else:#TODO
            raise Exception("pyllvm err: returning type that evaluates to list but not implemented yet")

        expr = self.visit(node)

        # malloc an array
        arrTy = llvm.core.Type.array(toLLVMTy(self.currFuncRetList[0]), self.currFuncRetList[1])
        m_ptr = self.builder.malloc_array(arrTy, llvm.core.Constant.int(llIntType, self.currFuncRetList[1]))# TODO-1: change to all types, not just int
        # copy all the values from the stack one into the heap
        zero = llvm.core.Constant.int(llIntType, 0)
        for i in range(self.currFuncRetList[1]):
            index = llvm.core.Constant.int(llIntType, i)
            # get alloc'd array values
            tmp0  = symbolTable.genUniqueSymbol(float)
            a = self.builder.gep(expr, [zero, index])
            a0 = self.builder.load(a, tmp0.name)

            # store values in malloc'd array
            m = self.builder.gep(m_ptr, [zero, index])
            self.builder.store(a0, m)
        # reset expr to the malloc'd array ptr
        return self.builder.ret(m_ptr)

    # returning a list works if the list is passed in. TODO-1
    #NOTE: arrays are passed by pointer, so if you construct an array within a function call and return it
    # you will end up passing a bad pointer. To get around this, as a temporary measure, if you absolutely must
    # return a constructed array in a function then it will be automatically malloc'd. Unfortunately this means
    # for now at least, that memory is gone and isn't going to be freed because everything else is on the stack.
    # So please avoid, but if you need to do it the functionality is there.
    def visitReturn(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        # get type of return node
        ty   = typer.inferType(node.value)

        if(ty==list):
            if self.currFuncRetType is None:
                self.currFuncRetType = ty
                self.prevFuncRetNode = node
            return self.emitMakeArray(node.value)


        # Return(Const(None))
        if isinstance(node.value, compiler.ast.Const):
            if node.value.value == None:
                self.currFuncRetType = void
                self.currFuncRetList = (None, 0)
                self.prevFuncRetNode = node
                return self.builder.ret_void()

        expr = self.visit(node.value)

        if self.currFuncRetType is None:
            self.currFuncRetType = ty
            self.prevFuncRetNode = node

        elif self.currFuncRetType != ty:
            raise Exception("pyllvm err: Different type for return expression: expected %s(lineno=%d, %s) but got %s(lineno=%d, %s)" % (self.currFuncRetType, self.prevFuncRetNode.lineno, self.prevFuncRetNode, ty, node.lineno, node))

        return self.builder.ret(expr)

    # in passing lists of variable length, there is the issue of setting the argument type
    # (since declaring vector requires the length and type, **even for a pointer to a vector**)
    # and even if it was possible to set up a function signature so that it would be able to take
    # pointers to vectors of different types and lengths, it would still need to be cast back 
    # into a specific type and length within the function in order to be used. Unless a new function
    # was generated for each different type of list argument that was passed in, there is not a neat
    # way to pass lists without providing some additional information in the declaration.
    #
    # point being, if you're going to pass lists as arguments to functions you need to specify how long
    # and what type of elements. This is done by setting the default argument to list<type><length> where
    # type is either 'i', 'f', 's', 'l' and length is an integer

    def mkFunctionSignature(self, retTy, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        # Argument should have default value which represents type of argument.
        if len(node.argnames) != len(node.defaults):
            raise Exception("pyllvm err: Function argument should have default values which represents type of the argument:", node)

        argLLTys = []

        for (name, tyname) in zip(node.argnames, node.defaults):

            assert isinstance(tyname, compiler.ast.Name)

            ty = typer.isNameOfFirstClassType(tyname.name)
            if ty is None:
                raise Exception("pyllvm err: Unknown name of type:", tyname.name)
            if ty==list:
                d = {'i':int, 'f':float, 's':str, 'l':list}
                if len(tyname.name) > 5 and d.has_key(tyname.name[4]):
                    listType = d[tyname.name[4]]
                    listLen = int(tyname.name[5:])
                    #TODO-1: change to array type (did: change llTy from vec to ptr2arr)
                    llTy = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(listType), listLen))
                else:
                    raise Exception("pyllvm err: Bad format for list default argument. list<type><len>", tyname.name)
            else:
                llTy = toLLVMTy(ty)

            # vector argument is passed by pointer.
            # if llTy == llFVec4Type:
            #     llTy = llFVec4PtrType

            argLLTys.append(llTy)

        funcLLVMTy = llvm.core.Type.function(retTy, argLLTys)
        func = llvm.core.Function.new(self.module, funcLLVMTy, node.name)

        # assign name for each arg
        for i, name in enumerate(node.argnames):

            # if llTy == llFVec4Type:
            #     argname = name + "_p"
            # else:
            #     argname = name
            argname = name

            func.args[i].name = argname


        return func

    def visitFunction(self, node):
        print ";----" + sys._getframe().f_code.co_name + ":" + node.name + "----"

        """
        Do nasty trick to handle return type of function correctly.

        We visit node AST two times.
        First pass just determines return type of the function
        (All LLVM code body generated are discarded).
        Then second pass we emit LLVM code body with return type found
        in the first pass.
        """

        # init
        self.currFuncRetType = None


        symbolTable.pushScope(node.name)
        retLLVMTy    = llVoidType # Dummy
        func         = self.mkFunctionSignature(retLLVMTy, node)
        entry        = func.append_basic_block("entry")
        builder      = llvm.core.Builder.new(entry)
        self.func    = func
        self.builder = builder
        self.funcs.append(func)

        # Add function argument to symblol table.
        # And emit function prologue.
        for i, (name, tyname) in enumerate(zip(node.argnames, node.defaults)):

            ty = typer.isNameOfFirstClassType(tyname.name)

            bufSym = symbolTable.genUniqueSymbol(ty)
            # 'if type of arguments are:'
            if ty==list:
                d = {'i':int, 'f':float, 's':str, 'l':list}
                if not d.has_key(tyname.name[4]):
                    raise Exception("pyllvm err: Bad format for list default argument. list<type><len>", tyname.name)
                # extract dims
                listType = d[tyname.name[4]]
                listLen = int(tyname.name[5:])
                #TODO-1: change to array type (did: change llTy from vec to ptr2arr)
                llTy = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(listType), listLen))
                allocaInst = self.builder.alloca(llTy, bufSym.name)
                storeInst  = self.builder.store(func.args[i], allocaInst)
                symbolTable.append(Symbol(name, ty, "variable", llstorage=allocaInst, dim=(listType, listLen)))
            else:
                llTy = toLLVMTy(ty)

                allocaInst = self.builder.alloca(llTy, bufSym.name)
                storeInst  = self.builder.store(func.args[i], allocaInst)
                symbolTable.append(Symbol(name, ty, "variable", llstorage=allocaInst))
        # visit actual function body, but throw out emitted LLVM, just keeping return type info
        self.visit(node.code)
        symbolTable.popScope()

        # Discard llvm code except for return type
        func.delete()
        del(self.funcs[-1])


        symbolTable.pushScope(node.name)
        if(self.currFuncRetType==list):
            #TODO-1: change to array type (did: change retLLVMTy from vec to ptr2arr)
            # used first pass to get type of return list, now set rettype to that one
            retLLVMTy    = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(self.currFuncRetList[0]), self.currFuncRetList[1]))
        else:
            retLLVMTy    = toLLVMTy(self.currFuncRetType)
        func             = self.mkFunctionSignature(retLLVMTy, node)
        entry            = func.append_basic_block("entry")
        builder          = llvm.core.Builder.new(entry)
        self.func        = func
        self.builder     = builder
        self.funcs.append(func)

        # Add function argument to symblol table.
        # And emit function prologue.
        for i, (name, tyname) in enumerate(zip(node.argnames, node.defaults)):

            ty = typer.isNameOfFirstClassType(tyname.name)
            bufSym = symbolTable.genUniqueSymbol(ty)

            if ty==list:
                d = {'i':int, 'f':float, 's':str, 'l':list}
                if not d.has_key(tyname.name[4]):
                    raise Exception("pyllvm err: Bad format for list default argument. list<type><len>", tyname.name)
                # extract dims
                listType = d[tyname.name[4]]
                listLen = int(tyname.name[5:])
                # TODO-1: change to array type
                llTy = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(listType), listLen))
                allocaInst = self.builder.alloca(llTy, bufSym.name)
                storeInst  = self.builder.store(func.args[i], allocaInst)
                symbolTable.append(Symbol(name, ty, "variable", llstorage=allocaInst, dim=(listType, listLen)))
            else:
                llTy = toLLVMTy(ty)
                allocaInst = self.builder.alloca(llTy, bufSym.name)
                storeInst  = self.builder.store(func.args[i], allocaInst)
                symbolTable.append(Symbol(name, ty, "variable", llstorage=allocaInst))
        # visit actual function body, for final time
        self.visit(node.code)

        if self.currFuncRetType is None:
            # Add ret void.
            self.builder.ret_void()
            self.currFuncRetType = void

        symbolTable.popScope()

        # Register function to symbol table
        print ";ADDING", node.name, "TO ST AS", self.currFuncRetType, " llstoroage=func"
        if(self.currFuncRetType==list):
            symbolTable.append(Symbol(node.name, self.currFuncRetType, "function", llstorage=func, dim=self.currFuncRetList))
        else:
            symbolTable.append(Symbol(node.name, self.currFuncRetType, "function", llstorage=func))



    def visitStmt(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        for node in node.nodes:

            self.visit(node)

    def visitAssign(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        if len(node.nodes) != 1:
            raise Exception("TODO:", node)

        rTy     = typer.inferType(node.expr)
        # if this is a list, will be a pointer. Otherwise a value
        rLLInst = self.visit(node.expr)
        lhsNode = node.nodes[0]
        lTy = None
        if isinstance(lhsNode, compiler.ast.AssName):
            sym = symbolTable.find(lhsNode.name)
            if sym is None:
                # The variable appears here firstly.

                # alloc storage

                # if array, already alloca'd in visit() so will set vlaue to pointer
                if(rTy==list):
                    listType = None
                    listLen = 0
                    # TODO-d: change types to array
                    if isinstance(node.expr, compiler.ast.List):
                        listType=typer.inferType(node.expr.nodes[0])
                        listLen=len(node.expr.nodes)
                        llTy = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(listType), listLen))
                        #llTy = llvm.core.Type.vector(toLLVMTy(typer.inferType(node.expr.nodes[0])), len(node.expr.nodes))
                    elif isinstance(node.expr, compiler.ast.Name):
                        listType, listLen = symbolTable.find(node.expr.name).getDim()
                        llTy = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(listType), listLen))
                    #    llTy = llvm.core.Type.vector(toLLVMTy(listType), listLen)
                    elif isinstance(node.expr, compiler.ast.CallFunc):
                        listType, listLen = symbolTable.find(node.expr.node.name).getDim()
                        llTy = llvm.core.Type.pointer(llvm.core.Type.array(toLLVMTy(listType), listLen))
                    #    llTy = llvm.core.Type.vector(toLLVMTy(listType), listLen)
                    else:
                        raise Exception("haven't implemented assigning all list types", node.expr)
                    # create space for LHS node of type llTy, addr in llStorage
                    llStorage = self.builder.alloca(llTy, lhsNode.name)

                    sym = Symbol(lhsNode.name, rTy, "variable", llstorage = llStorage, dim=(listType, listLen))
                    symbolTable.append(sym)
                else:
                    # get type of new value
                    llTy = toLLVMTy(rTy)
                    # create space for LHS node, addr in llStorage
                    llStorage = self.builder.alloca(llTy, lhsNode.name)
                    # create symbol for LHS, with name lhsNode.name and address of newly made space
                    sym = Symbol(lhsNode.name, rTy, "variable", llstorage = llStorage)
                    # add to symbol table
                    symbolTable.append(sym)

                lTy = rTy

            else:
                # symbol is already defined.
                lTy = sym.type


        if rTy != lTy:
            raise Exception("pyllvm err: TypeMismatch: lTy = %s, rTy = %s. Cannot dynamically reassign vars to different types" % (lTy, rTy))

        # get space for LHS node
        lSym = symbolTable.find(lhsNode.name)
        # store value of RHS into address of LHS
        # if this is list, hopefully storing the value of rLLInst into L
        storeInst = self.builder.store(rLLInst, lSym.llstorage)
        # No return
    def testRet(self, node):
       
       if isinstance(node, compiler.ast.Return):
           print ";FOUND RET"
           return (True, typer.inferType(node.value))
       elif isinstance(node, compiler.ast.Stmt):
            for i in node.nodes:
                d = self.testRet(i)
                if d[0]:
                    print ";FOUND RET IN STMT", i
                    return (True, typer.inferType(i))
            return (False, None)
       else:
           return (False, None)

    def visitIf(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        is_else = (node.else_ is not None)
        cond = self.visit(node.tests[0][0])
        then_ret, then_type = self.testRet(node.tests[0][1])
        if(is_else):
            else_ret, else_type = self.testRet(node.else_)
        # TODO: cast return value from cond to truth value
        condition_bool = self.builder.fcmp(llvm.core.FCMP_ONE, cond, llvm.core.Constant.real(llFloatType, 0), 'ifcond')
        # get function
        function = self.builder.basic_block.function
        
        # create blocks
        then_block = function.append_basic_block('if_then')
        if(is_else):
            else_block = function.append_basic_block('if_else')
        merge_block = function.append_basic_block('if_merge')
        if(is_else):
            self.builder.cbranch(condition_bool, then_block, else_block) 
        else:
            self.builder.cbranch(condition_bool, then_block, merge_block) 
            
        # emit then
        self.builder.position_at_end(then_block)
        symbolTable.pushScope("if_")
        then_val = self.visit(node.tests[0][1])
        symbolTable.popScope() 
        self.builder.branch(merge_block)
        # update then for phi 
        then_block = self.builder.basic_block
        if(is_else):
            # emit else
            self.builder.position_at_end(else_block)
            symbolTable.pushScope("else_")
            else_val = self.visit(node.else_)
            symbolTable.popScope()
            self.builder.branch(merge_block)
            else_block = self.builder.basic_block

        # emit merge
        self.builder.position_at_end(merge_block)
        if(is_else):
            if else_ret and then_ret:
                if(else_type != then_type):
                    raise Exception("unable to have if statement blocks that have different return types")
                # get null value and return
                return self.builder.unreachable()#self.builder.ret(llvm.core.Constant.null(else_type))
            elif not (not else_ret and not then_ret):
                raise Exception("unable to have if statement blocks that return if the else doesn't also return")
    
    
    def visitFor(self, node):
        print "VISITED FOR"
        print node

    def visitWhile(self, node):
        print ";VISITED WHILE"
        print ";----" + sys._getframe().f_code.co_name + "----"
        # get function
        function = self.builder.basic_block.function
        
        # create blocks
        start_while = function.append_basic_block('start_while')
        do_while = function.append_basic_block('do_while')
        end_while = function.append_basic_block('end_while')

        self.builder.branch(start_while)
        self.builder.position_at_end(start_while)

        cond = self.visit(node.test)
        # TODO: cast return value from cond to truth value
        condition_bool = self.builder.fcmp(llvm.core.FCMP_ONE, cond, llvm.core.Constant.real(llFloatType, 0), 'whilecond')

        self.builder.cbranch(condition_bool, do_while, end_while) 
        
        self.builder.position_at_end(do_while)
        while_body = self.visit(node.body)
        self.builder.branch(start_while)
        self.builder.position_at_end(end_while)
        #TODO: handle while-else?
    
    # emit vector comparisons (TODO?)
    def emitVCompare(self, op, lInst, rInst):
        print ";----" + sys._getframe().f_code.co_name + "----"

        d = { "==" : llvm.core.RPRED_OEQ
            , "!=" : llvm.core.RPRED_ONE
            , ">"  : llvm.core.RPRED_OGT
            , ">=" : llvm.core.RPRED_OGE
            , "<"  : llvm.core.RPRED_OLT
            , "<=" : llvm.core.RPRED_OLE
            }

        llop = d[op]

        i0 = llvm.core.Constant.int(llIntType, 0);
        i1 = llvm.core.Constant.int(llIntType, 1);
        i2 = llvm.core.Constant.int(llIntType, 2);
        i3 = llvm.core.Constant.int(llIntType, 3);
        vizero = llvm.core.Constant.vector([llvm.core.Constant.int(llIntType, 0)] * 4)

        tmp0  = symbolTable.genUniqueSymbol(float)
        tmp1  = symbolTable.genUniqueSymbol(float)
        tmp2  = symbolTable.genUniqueSymbol(float)
        tmp3  = symbolTable.genUniqueSymbol(float)
        tmp4  = symbolTable.genUniqueSymbol(float)
        tmp5  = symbolTable.genUniqueSymbol(float)
        tmp6  = symbolTable.genUniqueSymbol(float)
        tmp7  = symbolTable.genUniqueSymbol(float)
        le0   = self.builder.extract_element(lInst, i0, tmp0.name)
        le1   = self.builder.extract_element(lInst, i1, tmp1.name)
        le2   = self.builder.extract_element(lInst, i2, tmp2.name)
        le3   = self.builder.extract_element(lInst, i3, tmp3.name)
        re0   = self.builder.extract_element(rInst, i0, tmp4.name)
        re1   = self.builder.extract_element(rInst, i1, tmp5.name)
        re2   = self.builder.extract_element(rInst, i2, tmp6.name)
        re3   = self.builder.extract_element(rInst, i3, tmp7.name)

        ftmp0 = symbolTable.genUniqueSymbol(float)
        ftmp1 = symbolTable.genUniqueSymbol(float)
        ftmp2 = symbolTable.genUniqueSymbol(float)
        ftmp3 = symbolTable.genUniqueSymbol(float)

        f0 = self.builder.fcmp(llop, le0, re0, ftmp0.name)
        f1 = self.builder.fcmp(llop, le1, re1, ftmp1.name)
        f2 = self.builder.fcmp(llop, le2, re2, ftmp2.name)
        f3 = self.builder.fcmp(llop, le3, re3, ftmp3.name)

        # i1 -> i32
        ctmp0 = symbolTable.genUniqueSymbol(int)
        ctmp1 = symbolTable.genUniqueSymbol(int)
        ctmp2 = symbolTable.genUniqueSymbol(int)
        ctmp3 = symbolTable.genUniqueSymbol(int)
        c0 = self.builder.sext(f0, llIntType)
        c1 = self.builder.sext(f1, llIntType)
        c2 = self.builder.sext(f2, llIntType)
        c3 = self.builder.sext(f3, llIntType)

        # pack
        s0 = symbolTable.genUniqueSymbol(llIVec4Type)
        s1 = symbolTable.genUniqueSymbol(llIVec4Type)
        s2 = symbolTable.genUniqueSymbol(llIVec4Type)
        s3 = symbolTable.genUniqueSymbol(llIVec4Type)

        r0 = self.builder.insert_element(vizero, c0, i0, s0.name)
        r1 = self.builder.insert_element(r0    , c1, i1, s1.name)
        r2 = self.builder.insert_element(r1    , c2, i2, s2.name)
        r3 = self.builder.insert_element(r2    , c3, i3, s3.name)

        return r3

    def visitCompare(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        #print "; ", node.expr
        #print "; ", node.ops[0]

        lTy = typer.inferType(node.expr)
        rTy = typer.inferType(node.ops[0][1])

        if rTy != lTy:
            return llvm.core.Constant.real(llFloatType, 0.00)
            #raise Exception("ERR: TypeMismatch: lTy = %s, rTy = %s for %s, line %d" % (lTy, rTy, node, node.lineno))

        lLLInst = self.visit(node.expr)
        rLLInst = self.visit(node.ops[0][1])

        op  = node.ops[0][0]
        
        if rTy == vec:
            return self.emitVCompare(op, lLLInst, rLLInst)
        elif rTy == int:
            d = { "==" : llvm.core.ICMP_EQ
                , "!=" : llvm.core.ICMP_NE
                , ">"  : llvm.core.ICMP_UGT
                , ">=" : llvm.core.ICMP_UGE
                , "<"  : llvm.core.ICMP_ULT
                , "<=" : llvm.core.ICMP_ULE
                }
            result = self.builder.icmp(d[op], lLLInst, rLLInst, 'cmptmp')
            return self.builder.uitofp(result, llFloatType, 'booltmp')
        elif rTy == float:
            d = { "==" : llvm.core.FCMP_OEQ
                , "!=" : llvm.core.FCMP_ONE
                , ">"  : llvm.core.FCMP_OGT
                , ">=" : llvm.core.FCMP_OGE
                , "<"  : llvm.core.FCMP_OLT
                , "<=" : llvm.core.FCMP_OLE
                }
            result = self.builder.fcmp(d[op], lLLInst, rLLInst, 'cmptmp')
            return self.builder.uitofp(result, llFloatType, 'flttmp')
        else:  
            raise Exception("pyllvm err: unable to compare type " + rTy)

        #if op == "<":
            #print "muda"
        #elif op == ">":
            #print "muda"
        #else:
        

        if (op !="<") and (op != ">"):
            raise Exception("pyllvm err: Unknown operator:", op)

        raise Exception("pyllvm err: muda")

    def visitUnarySub(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        ty       = typer.inferType(node.expr)
        e        = self.visit(node.expr)
        zeroInst = llvm.core.Constant.null(toLLVMTy(ty))
        tmpSym   = symbolTable.genUniqueSymbol(ty)

        subInst = self.builder.sub(zeroInst, e, tmpSym.name)

        return subInst
    #TODO: is this ever used?
    def visitGetattr(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        d = { 'x' : llvm.core.Constant.int(llIntType, 0)
            , 'y' : llvm.core.Constant.int(llIntType, 1)
            , 'z' : llvm.core.Constant.int(llIntType, 2)
            , 'w' : llvm.core.Constant.int(llIntType, 3)
            }


        ty = typer.inferType(node)
        #print "; getattr: expr", node.expr
        #print "; getattr: attrname", node.attrname
        #print "; getattr: ty", ty

        rLLInst  = self.visit(node.expr)
        tmpSym   = symbolTable.genUniqueSymbol(ty)

        if len(node.attrname) == 1:
            # emit extract element
            s = node.attrname[0]

            inst = self.builder.extract_element(rLLInst, d[s], tmpSym.name)

        return inst



    def visitAdd(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        lTy = typer.inferType(node.left)
        rTy = typer.inferType(node.right)
        if rTy != lTy:
            raise Exception("pyllvm err: TypeMismatch: lTy = %s, rTy = %s for %s, line %d" % (lTy, rTy, node, node.lineno))

        lLLInst = self.visit(node.left)
        rLLInst = self.visit(node.right)
        
        tmpSym = symbolTable.genUniqueSymbol(lTy)

        if( lTy == float ):
            addInst = self.builder.fadd(lLLInst, rLLInst, tmpSym.name)
            return addInst

        addInst = self.builder.add(lLLInst, rLLInst, tmpSym.name)
        #print "; [AddOp] inst = ", addInst
        return addInst

    def visitSub(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        lTy = typer.inferType(node.left)
        rTy = typer.inferType(node.right)

        if rTy != lTy:
            raise Exception("pyllvm err: TypeMismatch: lTy = %s, rTy = %s for %s, line %d" % (lTy, rTy, node, node.lineno))

        lLLInst = self.visit(node.left)
        rLLInst = self.visit(node.right)

        tmpSym = symbolTable.genUniqueSymbol(lTy)

        if( lTy == float ):
            subInst = self.builder.fsub(lLLInst, rLLInst, tmpSym.name)
            return subInst
        subInst = self.builder.sub(lLLInst, rLLInst, tmpSym.name)
        #print "; [SubOp] inst = ", subInst

        return subInst


    def visitMul(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        lTy = typer.inferType(node.left)
        rTy = typer.inferType(node.right)

        if rTy != lTy:
            raise Exception("pyllvm err: TypeMismatch: lTy = %s, rTy = %s for %s, line %d" % (lTy, rTy, node, node.lineno))

        lLLInst = self.visit(node.left)
        rLLInst = self.visit(node.right)

        tmpSym = symbolTable.genUniqueSymbol(lTy)

        if( lTy == float ):
            mulInst = self.builder.fmul(lLLInst, rLLInst, tmpSym.name)
            return mulInst
        mulInst = self.builder.mul(lLLInst, rLLInst, tmpSym.name)
        #print "; [MulOp] inst = ", mulInst

        return mulInst


    def visitDiv(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        lTy = typer.inferType(node.left)
        rTy = typer.inferType(node.right)

        if rTy != lTy:
            raise Exception("pyllvm err: TypeMismatch: lTy = %s, rTy = %s for %s, line %d" % (lTy, rTy, node, node.lineno))

        lLLInst = self.visit(node.left)
        rLLInst = self.visit(node.right)

        tmpSym = symbolTable.genUniqueSymbol(lTy)

        if typer.isFloatType(lTy):
            divInst = self.builder.fdiv(lLLInst, rLLInst, tmpSym.name)
        else:
            divInst = self.builder.udiv(lLLInst, rLLInst, tmpSym.name)

        #print "; [DIvOp] inst = ", divInst

        return divInst

    def visitAnd(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        
        a = self.visit(node.nodes[0])
        a_sym = symbolTable.genUniqueSymbol(llTruthType)
        a_int = self.builder.fptoui(a, llTruthType, a_sym.name)
        
        for i in range(1, len(node.nodes)):
            b = self.visit(node.nodes[i])
            b_sym = symbolTable.genUniqueSymbol(llTruthType)
            b_int = self.builder.fptoui(b, llTruthType, b_sym.name)
            
            c_sym = symbolTable.genUniqueSymbol(llTruthType)
            c_int = self.builder.and_(a_int, b_int, c_sym.name)
            a_int = c_int
        
        return self.builder.uitofp(a_int, llFloatType, 'andtmp')
            


    def visitOr(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        
        a = self.visit(node.nodes[0])
        a_sym = symbolTable.genUniqueSymbol(llTruthType)
        a_int = self.builder.fptoui(a, llTruthType, a_sym.name)
        
        for i in range(1, len(node.nodes)):
            b = self.visit(node.nodes[i])
            b_sym = symbolTable.genUniqueSymbol(llTruthType)
            b_int = self.builder.fptoui(b, llTruthType, b_sym.name)
            
            c_sym = symbolTable.genUniqueSymbol(llTruthType)
            c_int = self.builder.or_(a_int, b_int, c_sym.name)
            a_int = c_int
        
        return self.builder.uitofp(a_int, llFloatType, 'ortmp')

    def visitNot(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        e = self.visit(node.expr) 
        e_sym = symbolTable.genUniqueSymbol(llTruthType)
        e_int = self.builder.fptoui(e, llTruthType, e_sym.name)

        not_sym = symbolTable.genUniqueSymbol(llTruthType)
        e_not = self.builder.not_(e_int, not_sym.name)

        ret_sym = symbolTable.genUniqueSymbol(llTruthType)
        return self.builder.uitofp(e_not, llFloatType, ret_sym.name)



    def handleInitializeTypeCall(self, ty, args):
        print ";----" + sys._getframe().f_code.co_name + "----"
        llty = toLLVMTy(ty)
        if llty == llFVec4Type:

            i0 = llvm.core.Constant.int(llIntType, 0);
            i1 = llvm.core.Constant.int(llIntType, 1);
            i2 = llvm.core.Constant.int(llIntType, 2);
            i3 = llvm.core.Constant.int(llIntType, 3);

            vf = llvm.core.Constant.vector([llvm.core.Constant.real(llFloatType, "0.0")] * 4)

            # args =  [List([float, float, float, float])]
            #      or [List(float)]
            if len(args)==4:
                elems = args
            else:
                elems =[args[0], args[0], args[0], args[0]]
            #else:
            #    elems = [args[0], args[0], args[0], args[0]]

            s0 = symbolTable.genUniqueSymbol(llFVec4Type)
            s1 = symbolTable.genUniqueSymbol(llFVec4Type)
            s2 = symbolTable.genUniqueSymbol(llFVec4Type)
            s3 = symbolTable.genUniqueSymbol(llFVec4Type)

            r0 = self.builder.insert_element(vf, elems[0] , i0, s0.name)
            r1 = self.builder.insert_element(r0, elems[1] , i1, s1.name)
            r2 = self.builder.insert_element(r1, elems[2] , i2, s2.name)
            r3 = self.builder.insert_element(r2, elems[3] , i3, s3.name)

            return r3

    def emitVSel(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        self.builder.call
        f3 = self.builder.call(func, [e3], ftmp3.name)
    def emitLen(self, node):
        if(typer.inferType(node)!=list):
            raise Exception("pyllvm err: calling len on nonlist")
        n = self.visit(node)
        if isinstance(node, compiler.ast.List):
            return len(node.nodes)
        elif isinstance(node, compiler.ast.Name):
            return symbolTable.find(node.name).getDim()[1]
        elif isinstance(node, compiler.ast.CallFunc):
            return symbolTable.find(node.node.name).getDim()[1]
        else:
            raise Exception("haven't handled list type for len", node)
    def visitCallFunc(self, node):
        print ";----" + sys._getframe().f_code.co_name + ": " + node.node.name + "----"
        assert isinstance(node.node, compiler.ast.Name)

        #print "; callfunc", node.args

        #args = [self.visit(a) for a in node.args]
        
        # special case for vec, since existing code expects entry as list but not type list
        if(node.node.name=='vec') and isinstance(node.args[0], compiler.ast.List):
            args = [self.visit(a) for a in node.args[0]]
        else:
            args = [self.visit(a) for a in node.args]
            # TODO: got rid of special casing to expand lists, well see if this breaks anything
       # special case for len, since it takes a variable argument
        if(node.node.name=='len'):
            l = self.emitLen(node.args[0])
            r = llvm.core.Constant.int(llIntType, l)
            return r
        #print "; callfuncafter", args
        #print "; callfuncafter: ty = ",ty

        #
        # value initialier?
        #
        #TODO: test this with anything other than Vec
        ty = typer.isNameOfFirstClassType(node.node.name)
        if ty:
            # int, float, vec, ...
            print ";in CALLFUNC len args = ", len(args)
            return self.handleInitializeTypeCall(ty, args)

        #
        # vector math function?
        #
        # UNCOMMENT:
        #orginal=comment start
        #ret = self.isVectorMathFunction(node.node.name)
        #if ret is not False:
        #    return self.emitVMath(ret[1], args)

        #
        # Special function?
        #
        #if (node.node.name == "vsel"):
        #    func = self.getExternalSymbolInstruction("vsel")
        #    tmp  = symbolTable.genUniqueSymbol(vec)

            #print "; ", args
         #   c    = self.builder.call(func, args, tmp.name)

         #   return c
        #original=commented end
        #
        # Defined in the source?
        #
        ty      = typer.inferType(node.node)
        
        funcSig = symbolTable.lookup(node.node.name)

        if funcSig.kind is not "function":
            raise Exception("pyllvm err: Symbol isn't registered as function:", node.node.name)

        # emit call
        if(ty == void):
            return self.builder.call(funcSig.llstorage, args)
        else:
            tmp  = symbolTable.genUniqueSymbol(ty)
            return self.builder.call(funcSig.llstorage, args, tmp.name)

        # if the type is void, then don't assign function call to anything

    def visitList(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"
        
        # get length and type of list
        lenList = len(node.nodes)
        if lenList==0:
            raise Exception("pyllvm err: Lists can't be empty (lists are not resizable)")
        tyList = typer.inferType(node.nodes[0])
        llNodes = []
        for n in node.nodes:
            nty = typer.inferType(n)
            if tyList!=nty:
                raise Exception("pyllvm err: Lists elements need to be of the same type")
            llNodes.append(self.visit(n))
        # emit list llvm
        # TODO-d: here change to construction of array
        arrTy = llvm.core.Type.array(toLLVMTy(tyList), lenList)
        l_ptr = self.builder.alloca_array(arrTy, llvm.core.Constant.int(llIntType, lenList))
        
        
        # populate list
        zero = llvm.core.Constant.int(llIntType, 0)
        for i in range(len(llNodes)):
            index = llvm.core.Constant.int(llIntType, i)
            #TODO-d: here change to array insert instead of insert_element (did: change gep + store)
            l = self.builder.gep(l_ptr, [zero, index])
            self.builder.store(llNodes[i], l)

        return l_ptr


    def visitSubscript(self, node):
        #TODO-d: change to array access
        print ";----" + sys._getframe().f_code.co_name + "----"
        n = self.visit(node.expr)
        index = self.visit(node.subs[0])
        zero = llvm.core.Constant.int(llIntType, 0)
        tmp0  = symbolTable.genUniqueSymbol(float)
        l = self.builder.gep(n, [zero, index])
        return self.builder.load(l, tmp0.name)
        #return self.builder.extract_element(n, index)

    #
    # Leaf
    #
    def visitName(self, node):
        print ";----" + sys._getframe().f_code.co_name + " : " + node.name + "----"
        sym = symbolTable.lookup(node.name)
        tmpSym = symbolTable.genUniqueSymbol(sym.type)

        # %tmp = load %name
        loadInst = self.builder.load(sym.llstorage, tmpSym.name)

        #print "; [Leaf] inst = ", loadInst
        return loadInst


    def visitDiscard(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        self.visit(node.expr)
        #
        # return None
        #

    def mkLLConstInst(self, ty, value):
        print ";----" + sys._getframe().f_code.co_name + " = " + str(value) + "----"

        # ty = typer.inferType(node)
        # print "; [Typer] %s => %s" % (str(node), str(ty))

        llTy   = toLLVMTy(ty)
        bufSym = symbolTable.genUniqueSymbol(ty)
        tmpSym = symbolTable.genUniqueSymbol(ty)

        # %tmp  = alloca ty
        # store ty val, %tmp
        # %inst = load ty, %tmp

        allocInst = self.builder.alloca(llTy, bufSym.name)

        llConst   = None
        if llTy   == llIntType:
            llConst = llvm.core.Constant.int(llIntType, value)

        elif llTy == llFloatType:
            llConst = llvm.core.Constant.real(llFloatType, value)

        elif llTy == llFVec4Type:
            print ";", value
            raise Exception("pyllvm err: muda")

        storeInst = self.builder.store(llConst, allocInst)
        loadInst  = self.builder.load(allocInst, tmpSym.name)

        #print ";", loadInst

        return loadInst

    def visitConst(self, node):
        print ";----" + sys._getframe().f_code.co_name + "----"

        ty = typer.inferType(node)

        return self.mkLLConstInst(ty, node.value)

    def emitCommonHeader(self):
        print ";----" + sys._getframe().f_code.co_name + "----"

        s = """ 
define <4 x float> @vsel(<4 x float> %a, <4 x float> %b, <4 x i32> %mask) {
entry:
    %a.i     = bitcast <4 x float> %a to <4 x i32>
    %b.i     = bitcast <4 x float> %b to <4 x i32>
    %tmp0    = and <4 x i32> %b.i, %mask
    %tmp.addr = alloca <4 x i32>
    store <4 x i32> <i32 -1, i32 -1, i32 -1, i32 -1>, <4 x i32>* %tmp.addr
    %allone  = load <4 x i32>* %tmp.addr
    %invmask = xor <4 x i32> %allone, %mask
    %tmp1    = and <4 x i32> %a.i, %invmask
    %tmp2    = or <4 x i32> %tmp0, %tmp1
    %r       = bitcast <4 x i32> %tmp2 to <4 x float>

    ret <4 x float> %r
}
        
        """
        return s

    #
    #
    # THIS IS WHERE HEADER DEFS LIVE
    def emitExternalSymbols(self):
        print ";----" + sys._getframe().f_code.co_name + "----"

        d = {
              'fabsf'  : ( llFloatType, [llFloatType] )
            , 'expf'   : ( llFloatType, [llFloatType] )
            , 'logf'   : ( llFloatType, [llFloatType] )
            , 'sqrtf'  : ( llFloatType, [llFloatType] )
            #, 'vsel'   : ( llFVec4Type, [llFVec4Type, llFVec4Type, llIVec4Type] )
            # FOR SOME REASON, REDEFINITION OF vsel BREAKS LLI, TODO:FIX
            }

        for k, v in d.items():
            fty = llvm.core.Type.function(v[0], v[1])
            f   = llvm.core.Function.new(self.module, fty, k)

            self.externals[k] = f
        print "; SYMBOL TABLE " + str(symbolTable)

    def getExternalSymbolInstruction(self, name):
        print ";----" + sys._getframe().f_code.co_name + "----"

        if self.externals.has_key(name):
            return self.externals[name]
        else:
            raise Exception("pyllvm err: Unknown external symbol:", name, self.externals)

    def isExternalSymbol(self, name):
        print ";----" + sys._getframe().f_code.co_name + "----"
        if self.externals.has_key(name):
            return True
        else:
            return False

    #
    # Vector math
    #
    def isVectorMathFunction(self, name):
        print ";----" + sys._getframe().f_code.co_name + "----"
        d = {
              'vabs'  : 'fabsf'
            , 'vexp'  : 'expf'
            , 'vlog'  : 'logf'
            , 'vsqrt' : 'sqrtf'
            }

        if d.has_key(name):
            return (True, d[name])
        else:
            return False

    def emitVMath(self, fname, llargs):
        print ";----" + sys._getframe().f_code.co_name + "----"
        """
        TODO: Use MUDA's optimized vector math function for LLVM.
        """

        i0    = llvm.core.Constant.int(llIntType, 0)
        i1    = llvm.core.Constant.int(llIntType, 1)
        i2    = llvm.core.Constant.int(llIntType, 2)
        i3    = llvm.core.Constant.int(llIntType, 3)
        vzero = llvm.core.Constant.vector([llvm.core.Constant.real(llFloatType, "0.0")] * 4)

        func = self.getExternalSymbolInstruction(fname)

        # Decompose vector element
        tmp0  = symbolTable.genUniqueSymbol(float)
        tmp1  = symbolTable.genUniqueSymbol(float)
        tmp2  = symbolTable.genUniqueSymbol(float)
        tmp3  = symbolTable.genUniqueSymbol(float)
        e0    = self.builder.extract_element(llargs[0], i0, tmp0.name)
        e1    = self.builder.extract_element(llargs[0], i1, tmp1.name)
        e2    = self.builder.extract_element(llargs[0], i2, tmp2.name)
        e3    = self.builder.extract_element(llargs[0], i3, tmp3.name)

        ftmp0 = symbolTable.genUniqueSymbol(float)
        ftmp1 = symbolTable.genUniqueSymbol(float)
        ftmp2 = symbolTable.genUniqueSymbol(float)
        ftmp3 = symbolTable.genUniqueSymbol(float)
        f0 = self.builder.call(func, [e0], ftmp0.name)
        f1 = self.builder.call(func, [e1], ftmp1.name)
        f2 = self.builder.call(func, [e2], ftmp2.name)
        f3 = self.builder.call(func, [e3], ftmp3.name)

        # pack
        s0 = symbolTable.genUniqueSymbol(llFVec4Type)
        s1 = symbolTable.genUniqueSymbol(llFVec4Type)
        s2 = symbolTable.genUniqueSymbol(llFVec4Type)
        s3 = symbolTable.genUniqueSymbol(llFVec4Type)

        r0 = self.builder.insert_element(vzero, f0, i0, s0.name)
        r1 = self.builder.insert_element(r0   , f1, i1, s1.name)
        r2 = self.builder.insert_element(r1   , f2, i2, s2.name)
        r3 = self.builder.insert_element(r2   , f3, i3, s3.name)
        return r3

        # r0 = self.builder.insert_element(vzero, f2, i2, s0.name)
        # r1 = self.builder.insert_element(r0   , e1, i1, s1.name)
        # r2 = self.builder.insert_element(r1   , e2, i0, s2.name)
        # return r2

    def emitVAbs(self, llargs):
        print ";----" + sys._getframe().f_code.co_name + "----"

        return self.emitVMath("fabsf", llargs)

def _test():
    import doctest
    doctest.testmod()
    sys.exit()

def py2llvm(filename):
    ast = compiler.parseFile(filename)
    print ";" +  str(ast)
    codegen = compiler.walk(ast, CodeGenLLVM())

    main = codegen.getString()
    header = codegen.emitCommonHeader()

    return str(main) + "\n" + str(header)

def main():

    if len(sys.argv) < 2:
        _test()

    ast = compiler.parseFile(sys.argv[1])
    #print ast

    compiler.walk(ast, CodeGenLLVM())


if __name__ == '__main__':
    main()

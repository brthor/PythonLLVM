from MUDA import *

# test visitReturn and visitFunction
def iret(i=int):
    return i+1
def fret(f=float):
    return 1.0000+f
def vret(v=vec):
    print v
    return v
def ifvret(i=int, v=vec, f=float):
    print f
    print v
    return i+i
def lretv5(lv5=listf5):
    return lv5
def lreti8(li8=listi8):
    print li8
    return li8
def lsubi(isub=int, lsi=listf5):
    return lsi[isub]
def lsubf(isubf=int, lsf=listi8):
    return lsf[isubf]+isubf
def nret():
    nret1= 5+5
    nret2 = nret1+5
def test_if():
    test_if1 = 4
    if(4==test_if1 and 5==5):
        test_if2 = -1
        test_if1 = 9
    if(test_if1==9 or 5==6):
        test_if2 = -3
        test_if1 = 11
    else:
        test_if2 = -4
        test_if1 = 0
    return test_if1#ret 11
def test_compare():
    a = (1==1)
    b = (1.00==1.00)
    c = (1>=0)
    d = (1.00>=0.00)
    e = (0<=1)
    fcp = (0.00 <= 1.00)
    g = (4!=6)
    h = (4.00!=6.00)
    z = a+b+c+d+e+fcp+g+h
    return z-7.00#ret 1.00
def test_while():
    test_while1 = 10
    while(test_while1>0):
        test_while1 = test_while1-1
    return test_while1#ret0
# test visitStmt
def test_ret1():
    x = [9,7,4]   
    return x
def test_ret2():
    return [6,7,8]
def test_ret3():
    return test_ret1()


def main():
    # test visitAssign
    ri = 5
    rf = 5.00
    rv = vec([1.00,2.00,3.00,4.00])
    v1 = vec(1.00)
    # test visitFunctionCall
    print iret(ri)                  #6
    print fret(rf)                  #6.00000
    print vret(rv)                  #vec[1.00,2.00,3.00,4.00] 
                                    #vec[1.00,2.00,3.00,4.00]
    print vret(v1)                  #vec[1.00,1.00,1.00,1.00]
                                    #vec[1.00,1.00,1.00,1,00]
    print ifvret(ri, rv, rf)        #5.00
                                    #vec[1.00,2.00,3.00,4.00]
                                    #10
    # test if/while/compare
    ift = test_if()
    whilet = test_while()
    comparet = test_compare()
   
    print(ift, whilet, comparet)    #11, 0, 1.00
    # test visitList
    f5 = [1.0,2.0,3.0,4.0,5.0]
    xf5 = f5
    zf5 = lretv5(xf5)               
    print f5                        #[1.0,2.0,3.0,4.0,5.0]
    print xf5                       #[1.0,2.0,3.0,4.0,5.0]
    print zf5                       #[1.0,2.0,3.0,4.0,5.0]
    i8 = [1,2,3,4,5,6,7,8]
    xi8 = i8
    zi8 = lreti8(i8)                #[1,2,3,4,5,6,7,8]
    print i8                        #[1,2,3,4,5,6,7,8]
    print zi8                       #[1,2,3,4,5,6,7,8]
    zlsi = lsubi(4, f5)
    zlsf = lsubf(2, xi8)
    print zlsi                      #5.0
    print zlsf                      #5
    print test_ret1()
    print test_ret2()
    print test_ret3()

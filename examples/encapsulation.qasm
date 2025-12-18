
include "stdgates.inc";


qubit[2] a;
qubit[2] b;

x a[0];
x b[0];
y b[0];


x b[1];
x a[0];
y a[0];


x a[0];
x a[1];
y a[1];

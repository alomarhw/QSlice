
include "stdgates.inc";


gate repeated_x a {
    x a;
    x a;
    x a;
    x a;
    x a;
    x a;
    x a;
}

qubit q;
repeated_x q;

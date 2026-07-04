pragma solidity ^0.4.25;


contract PrivateInvestment {

    function loggedTransfer(uint amount, address target) {
        if(!target.call.value(amount)()) throw;
    }
}

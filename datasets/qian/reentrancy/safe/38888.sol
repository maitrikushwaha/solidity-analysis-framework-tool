pragma solidity ^0.4.25;


contract FunFairSale {

    address public owner;

    function withdraw() {
        if (!owner.call.value(this.balance)()) throw;
    }
}

pragma solidity ^0.4.25;


contract ICOBuyer {

    address public sale;

    function buy() {
        require(sale.call.value(this.balance)());
    }
}

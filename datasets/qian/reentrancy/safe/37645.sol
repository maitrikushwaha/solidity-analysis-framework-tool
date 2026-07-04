pragma solidity ^0.4.25;


contract SFTToken {

	address public devETHDestination;

    function withdrawFunds() {
		if (0 == this.balance) throw;
		if (!devETHDestination.call.value(this.balance)()) throw;
	}
}

angular.module('aiddataDET')
.directive('detHeader', function($window) {
  return {
    restrict: "E",
    link: function(scope, element, attrs) {},
    templateUrl: "views/components/header.html",
    controller: function($scope, $stateParams, $state) {
      if ($state.current !== 'status') {

        $scope.process = [
          {
            name: 'map',
            display: 'Select Boundary',
            disabled: $state.current === 'checkout',
            icon: 'fa-map-pin'
          },
          {
            name: '',
            display: '/',
            disabled: '',
            icon: ''
          },
          {
            name: 'search',
            display: 'Search Datasets',
            disabled: $state.current === 'map',
            icon: 'fa-search'
          },
          {
            name: 'checkout',
            display: 'Checkout',
            disabled: $state.current === 'map',
            icon: 'fa-shopping-cart'
          }
        ];
        $scope.currentStep = $state.current.name;
        console.log($scope.currentStep);
      }

    }
  };
});

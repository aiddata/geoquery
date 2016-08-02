angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $log, $q, $state, $stateParams, $mdDialog, queryFactory) {
  $scope.filters = {};
  $scope.options = {};
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = [];
  $scope.geography = '';
  $scope.requestData = { name: 'New Request', editing: false, canReset: false };

  $scope.clearFilters = function () {
    if ($scope.dataset.type === 'release') {
      queryFactory.clearFilters();
    } else {
      queryFactory.clearOptions();
    }
  };

  $rootScope.$on('filters:updated', updateCounts);
  $rootScope.$on('options:updated', updateCounts);

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = queryFactory.getDataset();
    updateCounts();
  });

  $scope.addToCart = function() {
    $q.when(queryFactory.isUniq($scope.dataset, $scope.filters, $scope.options))
      .then(function(unique) {
        if (!unique) {
          return $q.reject({ message: 'This search is already in your cart'});
        }
        return queryFactory.generateQuery($scope.dataset.type);
      })
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      })
      .catch(function(err) {
        $log.error(err);
        showDialog(err.message, 'Error Adding To Cart');
      })
      .finally(function(){
        $scope.requestData.canAdd = false;
      });
  };

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.filters = queryFactory.filters;
    $scope.options = queryFactory.options;
    $scope.geography = queryFactory.getSubBoundary();

    if ($state.params.dataset) {
      $scope.dataset = queryFactory.getDataset();
      updateCounts();
    }
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    if (toParams.dataset) {
      $scope.dataset = queryFactory.getDataset(toParams.dataset);
      /* @TODO: Modify reset so this isn't necessary */
      $scope.filters = queryFactory.filters;
      $scope.options = queryFactory.options;
      updateCounts();
    }
  });

  function updateCounts() {
    if ($scope.dataset.type === 'raster') {
      $scope.requestData.canReset = false;
      $scope.requestData.canAdd = (
        _.size(_.get($scope.options, 'files')) &&
        _.size(_.get($scope.options, 'options.extract_types'))
      );

    } else {
      $scope.totals = _.pick(queryFactory.filterOptions, ['projects', 'locations']);
      $scope.requestData.canAdd = _.every(_.values($scope.totals));
      $scope.requestData.canReset = _.some(_.omit($scope.filters, 'dataset'), function(d, i) {
        return $scope.dataset.fields[i] && !_.isEqual(d, ['All']);
      });
    }
  }

  function showDialog(msg, label) {
    $mdDialog.show(
      $mdDialog.alert()
        .clickOutsideToClose(true)
        .title(msg)
        .ariaLabel(label)
        .ok('Got it!')
    );
  }

});
